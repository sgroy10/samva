const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, downloadMediaMessage, makeCacheableSignalKeyStore, Browsers, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs');
const QRCode = require('qrcode');
const sessionStore = require('./sessionStore');
const coreClient = require('./coreClient');

const SESSION_DIR = process.env.SESSION_DIR || path.resolve(__dirname, '../../data/sessions');
const logger = pino({ level: 'warn' });

// Active sessions: userId -> { socket, ownJid, qrDataUrl, reconnectAttempts }
const sessions = new Map();

// Rate limiting: userId -> lastSentTime
const sendTimestamps = new Map();
const SEND_INTERVAL_MS = 2000;

async function startSession(userId) {
  // Preserve reconnect count across restarts
  const existing = sessions.get(userId);
  const prevAttempts = existing ? existing.reconnectAttempts : 0;

  // Clean up old socket if exists
  if (existing && existing.socket) {
    try { existing.socket.end(); } catch (_) {}
  }

  console.log(`[sessionManager] Starting session for ${userId}`);

  const authDir = path.join(SESSION_DIR, userId);
  fs.mkdirSync(authDir, { recursive: true });

  const { state, saveCreds } = await useMultiFileAuthState(authDir);

  // Fetch latest WA version for compatibility
  let waVersion;
  try {
    const { version } = await fetchLatestBaileysVersion();
    waVersion = version;
  } catch (e) {
    console.log('[sessionManager] Could not fetch WA version, using default');
  }

  const sockOpts = {
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    printQRInTerminal: false,
    logger,
    browser: Browsers.ubuntu('Chrome'),
    generateHighQualityLinkPreview: false,
    syncFullHistory: false,
  };
  if (waVersion) sockOpts.version = waVersion;

  const socket = makeWASocket(sockOpts);

  const sessionData = {
    socket,
    ownJid: null,
    qrDataUrl: null,
    reconnectAttempts: prevAttempts,
    onboarded: false,
  };

  sessions.set(userId, sessionData);

  // Handle credentials update
  socket.ev.on('creds.update', saveCreds);

  // Handle connection updates
  socket.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      // Generate QR code as data URL
      try {
        const dataUrl = await QRCode.toDataURL(qr, { width: 300, margin: 2 });
        sessionData.qrDataUrl = dataUrl;
        console.log(`[sessionManager] QR generated for ${userId}`);
      } catch (err) {
        console.error(`[sessionManager] QR generation error:`, err.message);
      }
    }

    if (connection === 'open') {
      console.log(`[sessionManager] Connected: ${userId}`);
      sessionData.ownJid = socket.user?.id;
      sessionData.qrDataUrl = null;
      sessionData.reconnectAttempts = 0;

      sessionStore.updateSession(userId, {
        status: 'connected',
        phone: socket.user?.id?.split(':')[0] || '',
        lastSeen: new Date().toISOString(),
      });

      // Onboard if first connection
      if (!sessionData.onboarded) {
        sessionData.onboarded = true;
        const phone = socket.user?.id?.split(':')[0] || '';
        const pushName = socket.user?.name || '';
        const result = await coreClient.onboardUser(userId, phone, pushName);

        if (result.messages && result.messages.length > 0) {
          for (const msg of result.messages) {
            await rateLimitedSend(socket, sessionData.ownJid, msg);
          }
        }
      }
    }

    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

      console.log(`[sessionManager] Disconnected ${userId}: code=${statusCode}, reconnect=${shouldReconnect}`);

      sessionStore.updateSession(userId, { status: 'disconnected' });

      if (shouldReconnect && sessionData.reconnectAttempts < 5) {
        sessionData.reconnectAttempts++;
        const delay = Math.min(1000 * Math.pow(2, sessionData.reconnectAttempts), 60000);
        console.log(`[sessionManager] Reconnecting ${userId} in ${delay}ms (attempt ${sessionData.reconnectAttempts})`);
        setTimeout(() => startSession(userId), delay);
      } else if (!shouldReconnect) {
        console.log(`[sessionManager] Logged out: ${userId}. Cleaning up.`);
        sessions.delete(userId);
        sessionStore.updateSession(userId, { status: 'logged_out' });
      }
    }
  });

  // Handle incoming messages
  socket.ev.on('messages.upsert', async ({ messages: msgs, type }) => {
    if (type !== 'notify') return;

    for (const msg of msgs) {
      try {
        await handleIncomingMessage(userId, socket, sessionData, msg);
      } catch (err) {
        console.error(`[sessionManager] Message handler error for ${userId}:`, err.message);
      }
    }
  });

  return sessionData;
}

async function handleIncomingMessage(userId, socket, sessionData, msg) {
  // Skip if no message content
  if (!msg.message) return;

  const jid = msg.key.remoteJid;

  // Ignore status broadcasts
  if (jid === 'status@broadcast') return;

  // Ignore group messages
  if (jid?.endsWith('@g.us')) return;

  // Determine if self-chat
  const ownNumber = sessionData.ownJid?.split(':')[0] || '';
  const senderNumber = jid?.split('@')[0] || '';
  const isSelfChat = senderNumber === ownNumber;

  // Only process messages FROM the user (not messages they receive from others when it's not self-chat)
  // For non-self chats, only process incoming messages (fromMe = false means someone sent TO the user)
  // For self-chat, process messages the user sends to themselves
  if (!isSelfChat && msg.key.fromMe) return; // Skip outgoing messages to other people
  if (isSelfChat && !msg.key.fromMe) return; // In self-chat, only process messages the user sends

  // Extract text
  let text = '';
  let messageType = 'text';
  let imageBase64 = null;
  let audioBase64 = null;

  const msgContent = msg.message;

  if (msgContent.conversation) {
    text = msgContent.conversation;
  } else if (msgContent.extendedTextMessage?.text) {
    text = msgContent.extendedTextMessage.text;
  } else if (msgContent.imageMessage) {
    messageType = 'image';
    text = msgContent.imageMessage.caption || '';
    try {
      const buffer = await downloadMediaMessage(msg, 'buffer', {});
      imageBase64 = buffer.toString('base64');
    } catch (err) {
      console.error(`[sessionManager] Image download error:`, err.message);
    }
  } else if (msgContent.audioMessage || msgContent.pttMessage) {
    messageType = 'audio';
    try {
      const audioMsg = msgContent.audioMessage || msgContent.pttMessage;
      const buffer = await downloadMediaMessage(msg, 'buffer', {});
      audioBase64 = buffer.toString('base64');
    } catch (err) {
      console.error(`[sessionManager] Audio download error:`, err.message);
    }
  } else if (msgContent.documentMessage) {
    text = '[Document received]';
    messageType = 'document';
  } else {
    // Unsupported message type
    return;
  }

  // Skip empty messages
  if (!text && !imageBase64 && !audioBase64) return;

  console.log(`[sessionManager] Message from ${userId} (${isSelfChat ? 'self' : senderNumber}): ${text?.substring(0, 50) || `[${messageType}]`}`);

  // Send to Python API
  const senderJid = isSelfChat ? null : jid;
  const result = await coreClient.sendToApi(text, userId, messageType, imageBase64, audioBase64, senderJid);

  // Send reply
  if (result.reply) {
    const replyJid = isSelfChat ? sessionData.ownJid : jid;
    await rateLimitedSend(socket, replyJid, result.reply);
  }
}

async function rateLimitedSend(socket, jid, text) {
  if (!jid || !text) return;

  const now = Date.now();
  const lastSent = sendTimestamps.get(jid) || 0;
  const wait = Math.max(0, SEND_INTERVAL_MS - (now - lastSent));

  if (wait > 0) {
    await new Promise(resolve => setTimeout(resolve, wait));
  }

  try {
    await socket.sendMessage(jid, { text });
    sendTimestamps.set(jid, Date.now());
  } catch (err) {
    console.error(`[sessionManager] Send error to ${jid}:`, err.message);
  }
}

function getSession(userId) {
  return sessions.get(userId);
}

function getSessionStatus(userId) {
  const session = sessions.get(userId);
  const stored = sessionStore.getSession(userId);

  return {
    status: stored?.status || 'unknown',
    phone: stored?.phone || '',
    qrDataUrl: session?.qrDataUrl || null,
    hasQR: !!(session?.qrDataUrl),
  };
}

function getActiveCount() {
  let count = 0;
  for (const [, s] of sessions) {
    if (s.ownJid) count++;
  }
  return count;
}

async function reconnectAll() {
  const stored = sessionStore.getAllSessions();
  console.log(`[sessionManager] Reconnecting ${stored.length} saved sessions...`);

  for (const s of stored) {
    if (!sessions.has(s.userId)) {
      try {
        await startSession(s.userId);
        // Stagger reconnections
        await new Promise(resolve => setTimeout(resolve, 2000));
      } catch (err) {
        console.error(`[sessionManager] Failed to reconnect ${s.userId}:`, err.message);
      }
    }
  }
}

async function checkAllAlerts() {
  for (const [userId, sessionData] of sessions) {
    if (!sessionData.ownJid) continue;

    try {
      const result = await coreClient.checkAlerts(userId);
      if (result.alerts && result.alerts.length > 0) {
        for (const alert of result.alerts) {
          await rateLimitedSend(sessionData.socket, sessionData.ownJid, alert);
        }
      }
    } catch (err) {
      console.error(`[sessionManager] Alert check error for ${userId}:`, err.message);
    }
  }
}

async function sendAlertToUser(userId, message) {
  const session = sessions.get(userId);
  if (!session || !session.ownJid) {
    console.log(`[sessionManager] Cannot send alert to ${userId}: no active session`);
    return false;
  }
  try {
    await rateLimitedSend(session.socket, session.ownJid, message);
    return true;
  } catch (err) {
    console.error(`[sessionManager] Alert send failed for ${userId}:`, err.message);
    return false;
  }
}

module.exports = {
  startSession,
  getSession,
  getSessionStatus,
  getActiveCount,
  reconnectAll,
  checkAllAlerts,
  sendAlertToUser,
};
