require('dotenv').config({ path: ['.env', '../../.env'] });

const express = require('express');
const axios = require('axios');
const path = require('path');
const cron = require('node-cron');
const sessionManager = require('./sessionManager');
const sessionStore = require('./sessionStore');

const app = express();
const PORT = process.env.PORT || 3000;
const CORE_URL = process.env.CORE_API_URL || 'http://localhost:8000';

// Middleware
app.use(express.json({ limit: '50mb' }));
app.use(express.urlencoded({ extended: true }));

// Serve landing page
app.use(express.static(path.resolve(__dirname, '../../web/public')));

// --- Health ---
app.get('/health', (req, res) => {
  res.json({
    status: 'ok',
    sessions: sessionManager.getActiveCount(),
    uptime: process.uptime(),
  });
});

// --- Session Management ---
app.post('/sessions', async (req, res) => {
  try {
    const { userId } = req.body || {};
    const session = sessionStore.createSession(userId);
    await sessionManager.startSession(session.userId);

    res.json({
      userId: session.userId,
      pairToken: session.pairToken,
      status: session.status,
    });
  } catch (err) {
    console.error('[index] Session creation error:', err.message);
    res.status(500).json({ error: 'Failed to create session' });
  }
});

app.get('/sessions/:userId/status', (req, res) => {
  try {
    const { userId } = req.params;
    const status = sessionManager.getSessionStatus(userId);
    res.json(status);
  } catch (err) {
    console.error('[index] Session status error:', err.message);
    res.json({ status: 'unknown', phone: '', qrDataUrl: null, hasQR: false });
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

// --- Proxy /api/* to Python backend ---
app.all('/api/*', async (req, res) => {
  try {
    const targetPath = req.path.replace('/api', '');
    const url = `${CORE_URL}${targetPath}`;

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
});
