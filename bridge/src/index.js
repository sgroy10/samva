require('dotenv').config({ path: ['.env', '../../.env'] });

// Catch Baileys unhandled errors — prevent server crash
process.on('uncaughtException', (err) => {
  console.error(`[UNCAUGHT] ${err.message}`);
  // Don't exit — Baileys throws Connection Closed errors that are recoverable
});
process.on('unhandledRejection', (err) => {
  console.error(`[UNHANDLED] ${err?.message || err}`);
});

const express = require('express');
const axios = require('axios');
const path = require('path');
const cron = require('node-cron');
const sessionManager = require('./sessionManager');
const sessionStore = require('./sessionStore');
const coreClient = require('./coreClient');

const app = express();
const PORT = process.env.PORT || 3000;
const CORE_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// Middleware
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true }));

// Serve landing page
const webDir = path.resolve(__dirname, '../../web/public');
app.use(express.static(webDir));

// Static pages
app.get('/renew', (req, res) => res.sendFile(path.join(webDir, 'index.html')));
app.get('/privacy', (req, res) => res.sendFile(path.join(webDir, 'privacy.html')));
app.get('/terms', (req, res) => res.sendFile(path.join(webDir, 'terms.html')));
app.get('/contact', (req, res) => res.sendFile(path.join(webDir, 'contact.html')));
app.get('/admin', (req, res) => res.sendFile(path.join(webDir, 'admin.html')));

// --- Health ---
const DEPLOY_VERSION = '2026-04-22-v2'; // UPDATE EVERY DEPLOY
const DEPLOY_TIME = new Date().toISOString();
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    version: DEPLOY_VERSION,
    deployed_at: DEPLOY_TIME,
    sessions: sessionManager.getActiveCount(),
    uptime: Math.round(process.uptime()),
  });
});

// --- Test endpoint: proxy to internal API for testing ---
app.post('/test-message', async (req, res) => {
  try {
    const result = await coreClient.sendToApi(
      req.body.text || '',
      req.body.userId || '',
      req.body.messageType || 'text',
    );
    res.json(result);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- Debug PDF ---
app.get('/debug/pdf', async (req, res) => {
  try {
    const axios = require('axios');
    const resp = await axios.get('http://localhost:8000/debug/pdf', { timeout: 10000 });
    res.json(resp.data);
  } catch (err) { res.status(500).json({ error: err.message }); }
});

// --- Admin: deactivate broken skills ---
app.post('/admin/deactivate-skills', async (req, res) => {
  try {
    const axios = require('axios');
    const resp = await axios.post('http://localhost:8000/admin/deactivate-skills', req.body, { timeout: 10000 });
    res.json(resp.data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- Test TTS: generate voice and send to user's WhatsApp ---
app.post('/test-voice', async (req, res) => {
  try {
    const axios = require('axios');
    const resp = await axios.post('http://localhost:8000/test-voice', {
      user_id: req.body.userId,
      text: req.body.text || 'Hello! Main Sam hoon, aapka personal assistant.',
      voice_language: req.body.voice_language || 'hinglish',
    }, { timeout: 30000 });
    res.json(resp.data);
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- Session Management ---

// Create or resume a session
app.post('/sessions', async (req, res) => {
  try {
    const { userId } = req.body || {};

    // Check if session exists and is in a bad state — auto-clean
    const currentStatus = sessionManager.getSessionStatus(userId);
    if (['logged_out', 'deleted', 'conflict'].includes(currentStatus.status)) {
      console.log(`[index] Auto-cleaning stale session for ${userId} (was: ${currentStatus.status})`);
      sessionManager.deleteSession(userId);
    }

    const session = sessionStore.createSession(userId);
    await sessionManager.startSession(session.userId);

    res.json({
      userId: session.userId,
      pairToken: session.pairToken,
      status: 'pending',
    });
  } catch (err) {
    console.error('[index] Session creation error:', err.message);
    res.status(500).json({ error: 'Failed to create session' });
  }
});

// Get session status (with user-friendly messages)
app.get('/sessions/:userId/status', (req, res) => {
  try {
    const status = sessionManager.getSessionStatus(req.params.userId);
    res.json(status);
  } catch (err) {
    res.json({ status: 'unknown', statusMessage: 'Unknown status', phone: '', qrDataUrl: null, hasQR: false, needsReconnect: true });
  }
});

// Delete session fully (wipe auth files for fresh QR)
app.delete('/sessions/:userId', (req, res) => {
  sessionManager.deleteSession(req.params.userId);
  res.json({ ok: true });
});

// Reconnect — wipe stale session + create fresh one with new QR
app.post('/sessions/:userId/reconnect', async (req, res) => {
  try {
    const { userId } = req.params;
    console.log(`[index] Reconnect requested for ${userId}`);

    // Full wipe
    sessionManager.deleteSession(userId);

    // Wait a beat for cleanup
    await new Promise(r => setTimeout(r, 1000));

    // Fresh session
    const session = sessionStore.createSession(userId);
    await sessionManager.startSession(userId);

    res.json({ ok: true, status: 'pending', message: 'Fresh QR generating...' });
  } catch (err) {
    console.error('[index] Reconnect error:', err.message);
    res.status(500).json({ error: 'Reconnect failed. Try again.' });
  }
});

// --- Send message to a specific WhatsApp contact (owner confirmed) ---
app.post('/send-to-chat', async (req, res) => {
  const { userId, chatJid, text } = req.body;
  if (!userId || !chatJid || !text) return res.status(400).json({ error: 'Missing fields' });
  try {
    const sent = await sessionManager.sendMessageToChat(userId, chatJid, text);
    res.json({ sent });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- Send voice note to user (for testing + proactive voice) ---
app.post('/send-voice', async (req, res) => {
  const { userId, audioBase64, mimetype } = req.body;
  if (!userId || !audioBase64) return res.status(400).json({ error: 'Missing userId or audioBase64' });
  try {
    const sent = await sessionManager.sendVoiceToUser(userId, audioBase64, mimetype || 'audio/L16;rate=24000');
    res.json({ sent });
  } catch (err) {
    res.status(500).json({ error: err.message });
  }
});

// --- QR Code Page ---
app.get('/pair/:token', (req, res) => {
  const session = sessionStore.getSessionByToken(req.params.token);
  if (!session) {
    return res.status(404).send('Session not found');
  }

  res.send(`<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Samva — Scan QR Code</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body { font-family: 'DM Sans', sans-serif; background: #F5F2EC; display: flex; align-items: center; justify-content: center; min-height: 100vh; padding: 20px; }
    .card { background: white; border-radius: 24px; padding: 48px; text-align: center; max-width: 420px; width: 100%; box-shadow: 0 8px 32px rgba(0,0,0,0.08); }
    h1 { font-family: 'Fraunces', serif; font-size: 24px; margin-bottom: 8px; }
    h1 span { color: #C9A84C; }
    .subtitle { color: #8A8070; font-size: 14px; margin-bottom: 24px; }
    #qr-container { min-height: 300px; display: flex; align-items: center; justify-content: center; }
    #qr-container img { max-width: 280px; border-radius: 12px; }
    .loading { color: #8A8070; }
    .loading .spinner { width: 40px; height: 40px; border: 3px solid #eee; border-top: 3px solid #C9A84C; border-radius: 50%; animation: spin 1s linear infinite; margin: 0 auto 12px; }
    @keyframes spin { to { transform: rotate(360deg); } }
    .connected { color: #25D366; font-weight: 600; font-size: 18px; }
    .connected .check { font-size: 48px; margin-bottom: 12px; }
    .instructions { color: #8A8070; font-size: 13px; margin-top: 24px; line-height: 1.8; text-align: left; }
    .instructions strong { color: #0D0C0A; }
  </style>
  <link href="https://fonts.googleapis.com/css2?family=Fraunces:wght@600;700&family=DM+Sans:wght@400;500&display=swap" rel="stylesheet">
</head>
<body>
  <div class="card">
    <h1>Sam<span>va</span></h1>
    <p class="subtitle">Scan this QR code with WhatsApp</p>
    <div id="qr-container">
      <div class="loading">
        <div class="spinner"></div>
        <p>Generating QR code...</p>
      </div>
    </div>
    <div class="instructions">
      <strong>How to scan:</strong><br>
      1. Open WhatsApp on your phone<br>
      2. Tap <strong>Menu (⋮)</strong> or <strong>Settings</strong><br>
      3. Tap <strong>Linked Devices</strong><br>
      4. Tap <strong>Link a Device</strong><br>
      5. Point your phone at this QR code
    </div>
  </div>
  <script>
    const userId = '${session.userId}';
    const container = document.getElementById('qr-container');
    let pollInterval;

    async function checkStatus() {
      try {
        const resp = await fetch('/sessions/' + userId + '/status');
        const data = await resp.json();

        if (data.status === 'connected') {
          container.innerHTML = '<div class="connected"><div class="check">✓</div>Connected! Sam is alive on your WhatsApp.</div>';
          clearInterval(pollInterval);
        } else if (data.hasQR && data.qrDataUrl) {
          container.innerHTML = '<img src="' + data.qrDataUrl + '" alt="QR Code" />';
        }
      } catch (err) {
        console.error('Poll error:', err);
      }
    }

    checkStatus();
    pollInterval = setInterval(checkStatus, 3000);
  </script>
</body>
</html>`);
});

// --- Proxy /voice/* to Python backend (Twilio webhooks) ---
app.all('/voice/*', async (req, res) => {
  try {
    const targetPath = req.path;
    const url = `${CORE_URL}${targetPath}`;
    const response = await axios({
      method: req.method,
      url,
      data: req.body,
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      timeout: 30000,
      transformRequest: [(data) => {
        // Twilio sends form-encoded data
        if (typeof data === 'object') {
          return Object.entries(data).map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');
        }
        return data;
      }],
    });
    res.set('Content-Type', response.headers['content-type'] || 'application/xml');
    res.status(response.status).send(response.data);
  } catch (err) {
    console.error(`[Proxy] ${req.path} failed:`, err.message);
    res.set('Content-Type', 'application/xml');
    res.status(200).send(`<?xml version="1.0" encoding="UTF-8"?><Response><Say>Sorry, Sam is having trouble. Try WhatsApp.</Say></Response>`);
  }
});

// --- Proxy /api/* to Python backend ---
app.all('/api/*', async (req, res) => {
  try {
    const targetPath = req.path.replace('/api', '');
    const queryString = req.originalUrl.includes('?') ? req.originalUrl.split('?')[1] : '';
    const url = `${CORE_URL}${targetPath}${queryString ? '?' + queryString : ''}`;

    const config = {
      method: req.method,
      url,
      headers: { 'Content-Type': 'application/json' },
      timeout: 60000,
    };

    if (['POST', 'PUT', 'PATCH'].includes(req.method)) {
      config.data = req.body;
    }

    const response = await axios(config);
    res.status(response.status).json(response.data);
  } catch (err) {
    const status = err.response?.status || 500;
    const data = err.response?.data || { error: err.message };
    res.status(status).json(data);
  }
});

// --- Start Server ---
app.listen(PORT, async () => {
  console.log(`[Samva Bridge] Running on port ${PORT}`);
  console.log(`[Samva Bridge] Core API: ${CORE_URL}`);

  // Reconnect existing sessions
  try {
    await sessionManager.reconnectAll();
  } catch (err) {
    console.error('[Samva Bridge] Reconnect error:', err.message);
  }

  // Alert scheduler: every 15 minutes
  cron.schedule('*/15 * * * *', async () => {
    try {
      await sessionManager.checkAllAlerts();
    } catch (err) {
      console.error('[Samva Bridge] Alert scheduler error:', err.message);
    }
  });

  // Chat Intelligence: every 15 min — analyze inbox, flag urgent messages
  cron.schedule('*/15 * * * *', async () => {
    try {
      const resp = await coreClient.callCron('/cron/chat-intelligence');
      if (resp.count > 0) {
        console.log(`[Cron] Chat intelligence: ${resp.count} alerts`);
        for (const notif of (resp.notifications || [])) {
          await sessionManager.sendAlertToUser(notif.user_id, notif.message);
        }
      }
    } catch (err) {
      // Silent
    }
  });

  // Gold Price Alerts: every 15 min — alert jewellers on price moves
  cron.schedule('*/15 * * * *', async () => {
    try {
      const resp = await coreClient.callCron('/cron/gold-alerts');
      if (resp.count > 0) {
        console.log(`[Cron] Gold alerts: ${resp.count}`);
        for (const alert of (resp.alerts || [])) {
          await sessionManager.sendAlertToUser(alert.user_id, alert.message);
        }
      }
    } catch (err) {
      // Silent
    }
  });

  // Email Auto-Sync: every 30 min — fetch inbox, alert on important emails
  cron.schedule('*/30 * * * *', async () => {
    try {
      const resp = await coreClient.callCron('/cron/email-sync');
      if (resp.count > 0) {
        console.log(`[Cron] Email sync: ${resp.count} users with new mail`);
        for (const item of (resp.summaries || [])) {
          await sessionManager.sendAlertToUser(item.user_id, `📧 *New emails:*\n${item.summary}`);
        }
      }
    } catch (err) {
      // Silent
    }
  });

  // Pattern Watcher: every 15 min — detect patterns, propose behaviors
  cron.schedule('*/15 * * * *', async () => {
    try {
      const resp = await coreClient.callCron('/cron/pattern-watch');
      if (resp.count > 0) {
        console.log(`[Cron] Pattern engine: ${resp.count} users with activity`);
        // Send proposals to users via WhatsApp
        for (const result of (resp.results || [])) {
          if (result.proposals && result.proposals.length > 0) {
            for (const proposal of result.proposals) {
              await sessionManager.sendAlertToUser(result.user_id, proposal);
            }
          }
          // Execute active behaviors (auto-send gold brief, etc.)
          if (result.executions && result.executions.length > 0) {
            for (const exec of result.executions) {
              await sessionManager.sendAlertToUser(result.user_id, exec);
            }
          }
        }
      }
    } catch (err) {
      // Silent — don't spam logs
    }
  });

  // Soul Evolution: Sunday 11pm IST
  cron.schedule('0 23 * * 0', async () => {
    console.log('[Cron] Running soul evolution...');
    try {
      const resp = await coreClient.callCron('/cron/soul-evolution');
      console.log(`[Cron] Soul evolution: ${resp.evolved || 0} users evolved`);

      // Run network matching right after
      const matchResp = await coreClient.callCron('/cron/network-match');
      console.log(`[Cron] Network matching: ${matchResp.matches || 0} matches found`);

      // Send network match notifications via WhatsApp
      if (matchResp.notifications) {
        for (const notif of matchResp.notifications) {
          await sessionManager.sendAlertToUser(notif.user_id, notif.message);
        }
      }
    } catch (err) {
      console.error('[Cron] Soul evolution/network error:', err.message);
    }
  }, { timezone: 'Asia/Kolkata' });

  // Evolution notify: Monday 9am IST
  cron.schedule('0 9 * * 1', async () => {
    console.log('[Cron] Sending evolution notifications...');
    try {
      const resp = await coreClient.callCron('/cron/evolution-notify');
      if (resp.messages) {
        for (const item of resp.messages) {
          await sessionManager.sendAlertToUser(item.user_id, item.message);
        }
        console.log(`[Cron] Sent ${resp.count || 0} evolution messages`);
      }
    } catch (err) {
      console.error('[Cron] Evolution notify error:', err.message);
    }
  }, { timezone: 'Asia/Kolkata' });

  // Subscription check: daily 10am IST
  cron.schedule('0 10 * * *', async () => {
    console.log('[Cron] Checking subscriptions...');
    try {
      const resp = await coreClient.callCron('/cron/check-subscriptions');
      console.log(`[Cron] Subscriptions: ${resp.expired || 0} expired, ${resp.warned || 0} warned`);
      if (resp.notifications) {
        for (const notif of resp.notifications) {
          await sessionManager.sendAlertToUser(notif.user_id, notif.message);
        }
      }
    } catch (err) {
      console.error('[Cron] Subscription check error:', err.message);
    }
  }, { timezone: 'Asia/Kolkata' });

  // Auto-reply DISABLED — Sam NEVER sends messages to contacts without
  // explicit owner permission. Owner must say "Priya ko reply karo" in self-chat.
  // Chat intelligence reads messages silently and shows insights to owner.

  // Urgent reminder escalation: every 15 minutes
  cron.schedule('*/15 * * * *', async () => {
    try {
      const resp = await coreClient.callCron('/cron/urgent-escalations');
      if (resp.calls_made > 0) {
        console.log(`[Cron] Urgent calls made: ${resp.calls_made}`);
      }
    } catch (err) {
      // Silent — don't spam logs every 15 min
    }
  });

  // Morning brief as VOICE NOTE: every minute, check who needs brief
  cron.schedule('* * * * *', async () => {
    try {
      const resp = await coreClient.callCron('/cron/morning-brief-voice');
      if (resp.briefs && resp.briefs.length > 0) {
        for (const brief of resp.briefs) {
          // Send voice note if available
          if (brief.audio && brief.audio.data) {
            const sent = await sessionManager.sendVoiceToUser(
              brief.user_id, brief.audio.data, brief.audio.mimetype
            );
            if (!sent) {
              // Fallback to text
              await sessionManager.sendAlertToUser(brief.user_id, brief.text);
            }
          } else {
            // No audio — send as text
            await sessionManager.sendAlertToUser(brief.user_id, brief.text);
          }
        }
        console.log(`[Cron] Morning briefs: ${resp.briefs.length} sent`);
      }
    } catch (err) {
      // Silent — runs every minute
    }
  }, { timezone: 'Asia/Kolkata' });

  // Nightly voice diary: 10 PM IST
  cron.schedule('0 22 * * *', async () => {
    console.log('[Cron] Running nightly diary...');
    try {
      const resp = await coreClient.callCron('/cron/nightly-diary');
      if (resp.diaries && resp.diaries.length > 0) {
        for (const diary of resp.diaries) {
          if (diary.audio && diary.audio.data) {
            const sent = await sessionManager.sendVoiceToUser(
              diary.user_id, diary.audio.data, diary.audio.mimetype
            );
            if (!sent) {
              await sessionManager.sendAlertToUser(diary.user_id, diary.text);
            }
          } else {
            await sessionManager.sendAlertToUser(diary.user_id, diary.text);
          }
        }
        console.log(`[Cron] Nightly diaries: ${resp.diaries.length} sent`);
      }
    } catch (err) {
      console.error('[Cron] Nightly diary error:', err.message);
    }
  }, { timezone: 'Asia/Kolkata' });

  // FutureEcho: check daily at 8 PM IST (sends every 3 days per user)
  cron.schedule('0 20 * * *', async () => {
    console.log('[Cron] Checking FutureEcho...');
    try {
      const resp = await coreClient.callCron('/cron/future-echo');
      if (resp.echoes && resp.echoes.length > 0) {
        for (const echo of resp.echoes) {
          if (echo.audio && echo.audio.data) {
            const sent = await sessionManager.sendVoiceToUser(
              echo.user_id, echo.audio.data, echo.audio.mimetype
            );
            if (!sent) {
              await sessionManager.sendAlertToUser(echo.user_id, echo.text);
            }
          } else {
            await sessionManager.sendAlertToUser(echo.user_id, echo.text);
          }
        }
        console.log(`[Cron] FutureEcho: ${resp.echoes.length} sent`);
      }
    } catch (err) {
      console.error('[Cron] FutureEcho error:', err.message);
    }
  }, { timezone: 'Asia/Kolkata' });

  // Weekly report: Sunday 9 AM IST
  cron.schedule('0 9 * * 0', async () => {
    console.log('[Cron] Running weekly reports...');
    try {
      const resp = await coreClient.callCron('/cron/weekly-report');
      if (resp.reports && resp.reports.length > 0) {
        for (const report of resp.reports) {
          if (report.audio && report.audio.data) {
            const sent = await sessionManager.sendVoiceToUser(
              report.user_id, report.audio.data, report.audio.mimetype
            );
            if (!sent) {
              await sessionManager.sendAlertToUser(report.user_id, report.text);
            }
          } else {
            await sessionManager.sendAlertToUser(report.user_id, report.text);
          }
        }
        console.log(`[Cron] Weekly reports: ${resp.reports.length} sent`);
      }
    } catch (err) {
      console.error('[Cron] Weekly report error:', err.message);
    }
  }, { timezone: 'Asia/Kolkata' });

  // Session watchdog: every 5 minutes, check for dropped sessions
  cron.schedule('*/5 * * * *', async () => {
    try {
      await sessionManager.watchdogCheck();
    } catch (err) {
      console.error('[Watchdog] Error:', err.message);
    }
  });
});
