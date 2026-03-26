const { default: makeWASocket, useMultiFileAuthState, DisconnectReason, downloadMediaMessage, makeCacheableSignalKeyStore, Browsers, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const pino = require('pino');
const path = require('path');
const fs = require('fs');
const QRCode = require('qrcode');
const sessionStore = require('./sessionStore');
const coreClient = require('./coreClient');

const SESSION_DIR = process.env.SESSION_DIR || path.resolve(__dirname, '../../data/sessions');
const logger = pino({ level: 'warn' });

// Active sessions: userId -> sessionData
const sessions = new Map();

// Persistent reconnect counter (survives startSession recreations)
const reconnectCounters = new Map();

// Rate limiting: jid -> lastSentTime
const sendTimestamps = new Map();
const SEND_INTERVAL_MS = 2000;
const MAX_RECONNECT_ATTEMPTS = 5;

// ── Session Lifecycle ───────────────────────────────────────────

async function startSession(userId) {
  // Clean up old socket if exists
  const existing = sessions.get(userId);
  if (existing && existing.socket) {
    try { existing.socket.end(); } catch (_) {}
  }
  const prevAttempts = reconnectCounters.get(userId) || 0;

  console.log(`[session] Starting ${userId} (attempt ${prevAttempts})`);

  const authDir = path.join(SESSION_DIR, userId);
  fs.mkdirSync(authDir, { recursive: true });

  // Check if auth files exist — if not, this will be a fresh QR flow
  const hasCreds = fs.existsSync(path.join(authDir, 'creds.json'));

  let state, saveCreds;
  try {
    ({ state, saveCreds } = await useMultiFileAuthState(authDir));
  } catch (err) {
    // Corrupted auth files — wipe and retry
    console.log(`[session] Corrupted auth for ${userId}, wiping and retrying`);
    _wipeAuthDir(userId);
    ({ state, saveCreds } = await useMultiFileAuthState(authDir));
  }

  // Fetch latest WA version
  let waVersion;
  try {
    const { version } = await fetchLatestBaileysVersion();
    waVersion = version;
  } catch (_) {}

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
    onboarded: hasCreds, // Only onboard on truly fresh sessions
    disconnectReason: null,
  };

  sessions.set(userId, sessionData);

  socket.ev.on('creds.update', saveCreds);

  // ── Connection State Machine ────────────────────────────────
  socket.ev.on('connection.update', async (update) => {
    const { connection, lastDisconnect, qr } = update;

    // QR generated — store it
    if (qr) {
      try {
        sessionData.qrDataUrl = await QRCode.toDataURL(qr, { width: 300, margin: 2 });
        sessionStore.updateSession(userId, { status: 'waiting_qr' });
        console.log(`[session] QR ready for ${userId}`);
      } catch (err) {
        console.error(`[session] QR generation error:`, err.message);
      }
    }

    // Connected successfully
    if (connection === 'open') {
      console.log(`[session] CONNECTED: ${userId}`);
      sessionData.ownJid = socket.user?.id;
      sessionData.qrDataUrl = null;
      sessionData.reconnectAttempts = 0;
      sessionData.disconnectReason = null;
      reconnectCounters.set(userId, 0);

      sessionStore.updateSession(userId, {
        status: 'connected',
        phone: socket.user?.id?.split(':')[0] || '',
        lastSeen: new Date().toISOString(),
      });

      // Onboard on first-ever connection (not reconnect)
      if (!sessionData.onboarded) {
        sessionData.onboarded = true;
        try {
          const phone = socket.user?.id?.split(':')[0] || '';
          const pushName = socket.user?.name || '';
          const result = await coreClient.onboardUser(userId, phone, pushName);
          if (result.messages && result.messages.length > 0) {
            for (const msg of result.messages) {
              await rateLimitedSend(socket, sessionData.ownJid, msg);
            }
          }
        } catch (err) {
          console.error(`[session] Onboard error for ${userId}:`, err.message);
        }
      }
    }

    // Disconnected — handle every case
    if (connection === 'close') {
      const statusCode = lastDisconnect?.error?.output?.statusCode;
      const reason = lastDisconnect?.error?.message || 'unknown';
      console.log(`[session] DISCONNECTED ${userId}: code=${statusCode}, reason=${reason}`);

      // ── CASE 1: Logged out (401, device_removed) ──────────
      // User removed Sam from WhatsApp Linked Devices.
      // Auth files are invalid. Wipe everything. Next create gets fresh QR.
      if (statusCode === DisconnectReason.loggedOut || statusCode === 401) {
        console.log(`[session] LOGGED OUT: ${userId}. Wiping auth for fresh QR.`);
        sessions.delete(userId);
        _wipeAuthDir(userId);
        sessionStore.updateSession(userId, { status: 'logged_out' });
        return;
      }

      // ── CASE 2: Conflict (409) — opened on another device ─
      // Another Baileys instance took over. Don't reconnect aggressively.
      if (statusCode === 409) {
        console.log(`[session] CONFLICT: ${userId}. Another device took over. Waiting.`);
        sessions.delete(userId);
        sessionStore.updateSession(userId, { status: 'conflict' });
        return;
      }

      // ── CASE 3a: Stream error (515) — WhatsApp rejected stream ──
      // Do NOT auto-retry — creates infinite loop. Wait for user to reconnect.
      if (statusCode === 515) {
        console.log(`[session] STREAM ERROR (515): ${userId}. Waiting 60s before allowing retry.`);
        sessions.delete(userId);
        _wipeAuthDir(userId);
        sessionStore.updateSession(userId, { status: 'disconnected' });
        // Cool down — prevent immediate re-creation
        reconnectCounters.set(userId, MAX_RECONNECT_ATTEMPTS);
        // After 60s, allow reconnect
        setTimeout(() => {
          reconnectCounters.delete(userId);
          console.log(`[session] ${userId} cooldown expired. Ready for reconnect.`);
        }, 60000);
        return;
      }

      // ── CASE 3b: Bad session (405, 410, 440) ──────────────────
      // Session is corrupted. Wipe auth and auto-retry once with fresh QR.
      if ([405, 410, 440].includes(statusCode)) {
        console.log(`[session] BAD SESSION (${statusCode}): ${userId}. Wiping + fresh start.`);
        sessions.delete(userId);
        _wipeAuthDir(userId);
        sessionStore.updateSession(userId, { status: 'recovering' });
        setTimeout(() => {
          console.log(`[session] Auto-recovering ${userId} with fresh QR...`);
          startSession(userId);
        }, 5000);
        return;
      }

      // ── CASE 4: Temporary disconnect (network, restart, undefined) ─
      // Normal reconnect with exponential backoff, max 5 attempts.
      sessionStore.updateSession(userId, { status: 'reconnecting' });

      const attempts = (reconnectCounters.get(userId) || 0) + 1;
      reconnectCounters.set(userId, attempts);
      sessionData.reconnectAttempts = attempts;

      if (attempts < MAX_RECONNECT_ATTEMPTS) {
        const delay = Math.min(2000 * Math.pow(2, attempts), 60000);
        console.log(`[session] Reconnecting ${userId} in ${delay}ms (attempt ${attempts}/${MAX_RECONNECT_ATTEMPTS})`);
        setTimeout(() => startSession(userId), delay);
      } else {
        // Max attempts reached — wipe and stop (user can click Reconnect)
        console.log(`[session] MAX RECONNECTS reached for ${userId}. Wiping for fresh start.`);
        sessions.delete(userId);
        _wipeAuthDir(userId);
        reconnectCounters.delete(userId);
        sessionStore.updateSession(userId, { status: 'disconnected' });
      }
    }
  });

  // ── Message Handler ─────────────────────────────────────────
  socket.ev.on('messages.upsert', async ({ messages: msgs, type }) => {
    if (type !== 'notify') return;
    for (const msg of msgs) {
      try {
        await handleIncomingMessage(userId, socket, sessionData, msg);
      } catch (err) {
        console.error(`[session] Message error for ${userId}:`, err.message);
      }
    }
  });

  return sessionData;
}


// ── Message Processing ──────────────────────────────────────────

async function handleIncomingMessage(userId, socket, sessionData, msg) {
  if (!msg.message) return;
  const jid = msg.key.remoteJid;
  if (jid === 'status@broadcast') return;
  if (jid?.endsWith('@g.us')) return;

  const ownNumber = sessionData.ownJid?.split(':')[0] || '';
  const senderNumber = jid?.split('@')[0] || '';
  const isSelfChat = senderNumber === ownNumber;

  if (!isSelfChat && msg.key.fromMe) return;
  if (isSelfChat && !msg.key.fromMe) return;

  let text = '';
  let messageType = 'text';
  let imageBase64 = null;
  let audioBase64 = null;

  const mc = msg.message;
  if (mc.conversation) {
    text = mc.conversation;
  } else if (mc.extendedTextMessage?.text) {
    text = mc.extendedTextMessage.text;
  } else if (mc.imageMessage) {
    messageType = 'image';
    text = mc.imageMessage.caption || '';
    try {
      const buf = await downloadMediaMessage(msg, 'buffer', {});
      imageBase64 = buf.toString('base64');
    } catch (err) {
      console.error(`[session] Image download error:`, err.message);
    }
  } else if (mc.audioMessage || mc.pttMessage) {
    messageType = 'audio';
    try {
      const buf = await downloadMediaMessage(msg, 'buffer', {});
      audioBase64 = buf.toString('base64');
    } catch (err) {
      console.error(`[session] Audio download error:`, err.message);
    }
  } else if (mc.documentMessage) {
    text = '[Document received]';
    messageType = 'document';
  } else {
    return;
  }

  if (!text && !imageBase64 && !audioBase64) return;

  console.log(`[session] ${userId} (${isSelfChat ? 'self' : senderNumber}): ${text?.substring(0, 50) || `[${messageType}]`}`);

  const senderJid = isSelfChat ? null : jid;
  const result = await coreClient.sendToApi(text, userId, messageType, imageBase64, audioBase64, senderJid);

  if (result.reply) {
    const replyJid = isSelfChat ? sessionData.ownJid : jid;

    // Check if reply contains image data from JewelCraft/GemLens
    if (result.reply.includes('__IMAGE__')) {
      const parts = result.reply.split('__IMAGE__');
      const textPart = parts[0].trim();
      const imageData = parts[1].trim();

      // Send text part first if any
      if (textPart) {
        await rateLimitedSend(socket, replyJid, textPart);
      }

      // Send image
      if (imageData) {
        try {
          // imageData is a data URI: data:image/png;base64,...
          const base64 = imageData.includes(',') ? imageData.split(',')[1] : imageData;
          const buffer = Buffer.from(base64, 'base64');
          await socket.sendMessage(replyJid, {
            image: buffer,
            mimetype: 'image/png',
            caption: textPart || '',
          });
          console.log(`[session] Sent image to ${replyJid} (${(buffer.length / 1024).toFixed(0)}KB)`);
        } catch (imgErr) {
          console.error(`[session] Image send failed:`, imgErr.message);
          await rateLimitedSend(socket, replyJid, 'Image generate ho gayi but send nahi ho paayi. Thodi der mein try karo.');
        }
      }
    } else {
      await rateLimitedSend(socket, replyJid, result.reply);
    }
  }
}


// ── Utilities ───────────────────────────────────────────────────

async function rateLimitedSend(socket, jid, text) {
  if (!jid || !text) return;
  const now = Date.now();
  const lastSent = sendTimestamps.get(jid) || 0;
  const wait = Math.max(0, SEND_INTERVAL_MS - (now - lastSent));
  if (wait > 0) await new Promise(r => setTimeout(r, wait));

  try {
    await socket.sendMessage(jid, { text });
    sendTimestamps.set(jid, Date.now());
  } catch (err) {
    console.error(`[session] Send error to ${jid}:`, err.message);
  }
}

function _wipeAuthDir(userId) {
  const authDir = path.join(SESSION_DIR, userId);
  try { fs.rmSync(authDir, { recursive: true, force: true }); } catch (_) {}
  console.log(`[session] Auth wiped: ${userId}`);
}

function getSession(userId) {
  return sessions.get(userId);
}

function getSessionStatus(userId) {
  const session = sessions.get(userId);
  const stored = sessionStore.getSession(userId);
  const status = stored?.status || 'unknown';

  // Build user-friendly status message
  let statusMessage = '';
  if (status === 'connected') statusMessage = 'Sam is active on your WhatsApp';
  else if (status === 'waiting_qr') statusMessage = 'Scan the QR code with WhatsApp';
  else if (status === 'reconnecting') statusMessage = 'Reconnecting to WhatsApp...';
  else if (status === 'recovering') statusMessage = 'Session recovering — new QR coming...';
  else if (status === 'logged_out') statusMessage = 'Disconnected. Click "Reconnect" to get a new QR code.';
  else if (status === 'conflict') statusMessage = 'Session conflict. Click "Reconnect" to fix.';
  else if (status === 'disconnected') statusMessage = 'Disconnected. Click "Reconnect" to get a new QR code.';

  return {
    status,
    statusMessage,
    phone: stored?.phone || '',
    qrDataUrl: session?.qrDataUrl || null,
    hasQR: !!(session?.qrDataUrl),
    needsReconnect: ['logged_out', 'disconnected', 'conflict', 'deleted'].includes(status),
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
  const reconnectable = stored.filter(s =>
    s.status && !['logged_out', 'deleted'].includes(s.status)
  );
  console.log(`[session] Reconnecting ${reconnectable.length}/${stored.length} saved sessions...`);

  for (const s of reconnectable) {
    if (!sessions.has(s.userId)) {
      try {
        await startSession(s.userId);
        await new Promise(r => setTimeout(r, 2000));
      } catch (err) {
        console.error(`[session] Reconnect failed ${s.userId}:`, err.message);
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
      console.error(`[session] Alert check error for ${userId}:`, err.message);
    }
  }
}

function deleteSession(userId) {
  const session = sessions.get(userId);
  if (session && session.socket) {
    try { session.socket.end(); } catch (_) {}
  }
  sessions.delete(userId);
  reconnectCounters.delete(userId);
  _wipeAuthDir(userId);
  sessionStore.updateSession(userId, { status: 'deleted' });
  console.log(`[session] Session fully deleted: ${userId}`);
}

async function sendAlertToUser(userId, message) {
  const session = sessions.get(userId);
  if (!session || !session.ownJid) {
    console.log(`[session] Cannot send alert to ${userId}: no active session`);
    return false;
  }
  try {
    await rateLimitedSend(session.socket, session.ownJid, message);
    return true;
  } catch (err) {
    console.error(`[session] Alert send failed for ${userId}:`, err.message);
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
  deleteSession,
};
