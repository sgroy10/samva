/**
 * Samva Session Manager — matches JewelClaw v7 (post-LID fix).
 * Baileys v7.0.0-rc.9 required for current WhatsApp protocol.
 *
 * KEY: WhatsApp now uses LID (@lid) for linked device self-chat.
 * Must store both sock.user.id (phone JID) and sock.user.lid (LID).
 * Reply to LID first, fallback to phone JID.
 */

const { makeWASocket, useMultiFileAuthState, DisconnectReason, Browsers, fetchLatestBaileysVersion, downloadMediaMessage } = require('@whiskeysockets/baileys');
const pino = require('pino');
const QRCode = require('qrcode');
const path = require('path');
const fs = require('fs');
const sessionStore = require('./sessionStore');
const coreClient = require('./coreClient');

const SESSION_DIR = process.env.SESSION_DIR || path.resolve(__dirname, '../../data/sessions');
const MAX_SESSIONS = 100;

const activeSessions = new Map();
let waVersion = null;

const sendTimestamps = new Map();
const SEND_INTERVAL_MS = 2000;

function normalizeJid(jid) {
    if (!jid) return '';
    return jid.replace(/:(\d+)@/, '@');
}

async function fetchVersion() {
    try {
        const v = await fetchLatestBaileysVersion();
        waVersion = v.version;
        console.log(`[session] WA version: ${waVersion.join('.')}`);
    } catch (e) {
        console.log('[session] Could not fetch WA version, using default');
    }
}

async function startSession(userId) {
    if (activeSessions.has(userId)) return;
    if (activeSessions.size >= MAX_SESSIONS) {
        throw new Error('Max sessions reached');
    }

    const sessionDir = path.join(SESSION_DIR, userId);
    if (!fs.existsSync(sessionDir)) fs.mkdirSync(sessionDir, { recursive: true });
    if (!waVersion) await fetchVersion();

    const { state, saveCreds } = await useMultiFileAuthState(sessionDir);

    // Match JewelClaw's exact config — v7 + Windows Desktop + no history sync
    const sockOpts = {
        auth: state,
        browser: Browsers.windows('Desktop'),
        shouldSyncHistoryMessage: () => false,
        syncFullHistory: false,
        fireInitQueries: true,
        markOnlineOnConnect: false,
        logger: pino({ level: 'silent' }),
    };
    if (waVersion) sockOpts.version = waVersion;

    const sock = makeWASocket(sockOpts);
    const sessionData = {
        socket: sock,
        ownJid: '',      // Phone JID: 919876543210@s.whatsapp.net
        ownLid: '',      // Linked ID: 5550123456@lid (new protocol)
        qrDataUrl: null,
        saveCreds,
        onboarded: false,
    };
    activeSessions.set(userId, sessionData);

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log(`[session] QR generated for ${userId}`);
            try {
                sessionData.qrDataUrl = await QRCode.toDataURL(qr, { width: 400, margin: 2 });
            } catch (err) {
                console.error(`[session] QR error:`, err.message);
            }
            sessionStore.updateSession(userId, { status: 'waiting_qr' });
        }

        if (connection === 'open') {
            // Store BOTH phone JID and LID — critical for self-chat detection
            sessionData.ownJid = normalizeJid(sock.user?.id || '');
            sessionData.ownLid = normalizeJid(sock.user?.lid || '');
            sessionData.qrDataUrl = null;

            const phone = sessionData.ownJid.split('@')[0].split(':')[0] || '';
            console.log(`[session] CONNECTED ${userId} | JID: ${sessionData.ownJid} | LID: ${sessionData.ownLid}`);

            sessionStore.updateSession(userId, {
                status: 'connected',
                phone: phone,
                lastSeen: new Date().toISOString(),
            });

            // Onboard on first connection
            if (!sessionData.onboarded) {
                sessionData.onboarded = true;
                setTimeout(async () => {
                    try {
                        const pushName = sock.user?.name || '';
                        const result = await coreClient.onboardUser(userId, phone, pushName);
                        if (result.messages && result.messages.length > 0) {
                            const replyJid = getReplyJid(sessionData);
                            for (const msg of result.messages) {
                                await rateLimitedSend(sock, replyJid, msg);
                                await new Promise(r => setTimeout(r, 1500));
                            }
                        }
                    } catch (err) {
                        console.error(`[session] Onboard error for ${userId}:`, err.message);
                    }
                }, 3000);
            }
        }

        if (connection === 'close') {
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
            console.log(`[session] Disconnected ${userId} (code: ${statusCode})`);

            activeSessions.delete(userId);

            if (shouldReconnect) {
                sessionStore.updateSession(userId, { status: 'reconnecting' });
                setTimeout(() => startSession(userId), 3000);
            } else {
                sessionStore.updateSession(userId, { status: 'disconnected' });
                const authDir = path.join(SESSION_DIR, userId);
                try { fs.rmSync(authDir, { recursive: true, force: true }); } catch (_) {}
            }
        }
    });

    sock.ev.on('messages.upsert', async ({ messages: msgs, type }) => {
        if (type !== 'notify') return;
        for (const msg of msgs) {
            try {
                await handleIncomingMessage(userId, sock, sessionData, msg);
            } catch (err) {
                console.error(`[session] Message error for ${userId}:`, err.message);
            }
        }
    });
}

// Reply to LID first (new protocol), fallback to phone JID
function getReplyJid(sessionData) {
    return sessionData.ownLid || sessionData.ownJid;
}

async function handleIncomingMessage(userId, socket, sessionData, msg) {
    if (!msg.message) return;
    const remoteJid = normalizeJid(msg.key.remoteJid || '');
    if (remoteJid === 'status@broadcast') return;
    if (remoteJid.endsWith('@g.us')) return;

    const fromMe = msg.key.fromMe === true;

    // LID-aware self-chat detection — checks BOTH formats
    const isSelfChat = fromMe && (
        remoteJid === sessionData.ownJid ||
        (sessionData.ownLid && remoteJid === sessionData.ownLid) ||
        remoteJid.endsWith('@lid')
    );

    // For non-self chats: only process incoming messages (someone messaging the user)
    // For self-chat: only process messages the user sends to themselves
    if (!isSelfChat && fromMe) return;
    if (isSelfChat && !fromMe) return;

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
    } else {
        return;
    }

    if (!text && !imageBase64 && !audioBase64) return;

    console.log(`[session] ${userId} (${isSelfChat ? 'self' : remoteJid.split('@')[0]}): ${text?.substring(0, 50) || `[${messageType}]`}`);

    const senderJid = isSelfChat ? null : remoteJid;
    const result = await coreClient.sendToApi(text, userId, messageType, imageBase64, audioBase64, senderJid);

    if (result.reply) {
        const replyJid = isSelfChat ? getReplyJid(sessionData) : remoteJid;

        // Send voice note reply if API returned audio (user sent voice → Sam speaks back)
        if (result.audio && result.audio.data) {
            try {
                const audioBuf = Buffer.from(result.audio.data, 'base64');
                await socket.sendMessage(replyJid, {
                    audio: audioBuf,
                    mimetype: result.audio.mimetype || 'audio/mp4',
                    ptt: true,  // This makes it a WhatsApp voice note (blue play button)
                });
                console.log(`[session] Sent voice reply (${(audioBuf.length / 1024).toFixed(0)}KB)`);
            } catch (audioErr) {
                console.error(`[session] Voice reply failed:`, audioErr.message);
                // Fallback to text
                await rateLimitedSend(socket, replyJid, result.reply);
            }
        } else if (result.reply.includes('__IMAGE__')) {
            const parts = result.reply.split('__IMAGE__');
            const textPart = parts[0].trim();
            const imageData = parts[1].trim();

            if (textPart) await rateLimitedSend(socket, replyJid, textPart);
            if (imageData) {
                try {
                    const base64 = imageData.includes(',') ? imageData.split(',')[1] : imageData;
                    const buffer = Buffer.from(base64, 'base64');
                    await socket.sendMessage(replyJid, { image: buffer, mimetype: 'image/png' });
                    console.log(`[session] Sent image (${(buffer.length / 1024).toFixed(0)}KB)`);
                } catch (imgErr) {
                    console.error(`[session] Image send failed:`, imgErr.message);
                }
            }
        } else {
            await rateLimitedSend(socket, replyJid, result.reply);
        }
    }
}

async function rateLimitedSend(socket, jid, text) {
    if (!jid || !text) return;
    const now = Date.now();
    const lastSent = sendTimestamps.get(jid) || 0;
    const wait = Math.max(0, SEND_INTERVAL_MS - (now - lastSent));
    if (wait > 0) await new Promise(r => setTimeout(r, wait));

    const MAX_LEN = 3500;
    if (text.length <= MAX_LEN) {
        await socket.sendMessage(jid, { text });
    } else {
        let remaining = text;
        while (remaining.length > 0) {
            let splitAt = remaining.lastIndexOf('\n', MAX_LEN);
            if (splitAt <= 0) splitAt = MAX_LEN;
            await socket.sendMessage(jid, { text: remaining.substring(0, splitAt) });
            remaining = remaining.substring(splitAt).trimStart();
            if (remaining) await new Promise(r => setTimeout(r, 500));
        }
    }
    sendTimestamps.set(jid, Date.now());
}

function getSessionStatus(userId) {
    const session = activeSessions.get(userId);
    const stored = sessionStore.getSession(userId);
    const status = stored?.status || 'unknown';
    return {
        status,
        statusMessage: status === 'connected' ? 'Sam is active' :
                        status === 'waiting_qr' ? 'Scan the QR code with WhatsApp' :
                        status === 'reconnecting' ? 'Reconnecting...' :
                        'Disconnected',
        phone: stored?.phone || '',
        qrDataUrl: session?.qrDataUrl || null,
        hasQR: !!(session?.qrDataUrl),
        needsReconnect: ['disconnected', 'logged_out', 'deleted'].includes(status),
    };
}

function deleteSession(userId) {
    const session = activeSessions.get(userId);
    if (session?.socket) try { session.socket.end(); } catch (_) {}
    activeSessions.delete(userId);
    const authDir = path.join(SESSION_DIR, userId);
    try { fs.rmSync(authDir, { recursive: true, force: true }); } catch (_) {}
    sessionStore.updateSession(userId, { status: 'deleted' });
    console.log(`[session] Deleted: ${userId}`);
}

function getActiveCount() { return activeSessions.size; }

async function reconnectAll() {
    await fetchVersion();
    const stored = sessionStore.getAllSessions();
    const reconnectable = stored.filter(s => s.status && !['logged_out', 'deleted', 'disconnected'].includes(s.status));
    console.log(`[session] Reconnecting ${reconnectable.length}/${stored.length} sessions...`);
    for (const s of reconnectable) {
        const hasCreds = fs.existsSync(path.join(SESSION_DIR, s.userId, 'creds.json'));
        if (hasCreds) {
            try { await startSession(s.userId); await new Promise(r => setTimeout(r, 2000)); }
            catch (err) { console.error(`[session] Reconnect failed ${s.userId}:`, err.message); }
        }
    }
}

async function checkAllAlerts() {
    for (const [userId, sd] of activeSessions) {
        if (!sd.ownJid && !sd.ownLid) continue;
        try {
            const result = await coreClient.checkAlerts(userId);
            if (result.alerts?.length > 0) {
                const jid = getReplyJid(sd);
                for (const alert of result.alerts) await rateLimitedSend(sd.socket, jid, alert);
            }
        } catch (err) { console.error(`[session] Alert error ${userId}:`, err.message); }
    }
}

async function sendAlertToUser(userId, message) {
    const sd = activeSessions.get(userId);
    if (!sd) return false;
    try { await rateLimitedSend(sd.socket, getReplyJid(sd), message); return true; }
    catch (err) { console.error(`[session] Alert send failed ${userId}:`, err.message); return false; }
}

module.exports = { startSession, getSessionStatus, getActiveCount, reconnectAll, checkAllAlerts, sendAlertToUser, deleteSession };
