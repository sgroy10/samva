const axios = require('axios');

const CORE_URL = process.env.CORE_API_URL || 'http://localhost:8000';

const client = axios.create({
  baseURL: CORE_URL,
  timeout: 60000,
  headers: { 'Content-Type': 'application/json' },
});

async function sendToApi(text, userId, messageType = 'text', imageBase64 = null, audioBase64 = null, senderJid = null) {
  try {
    const resp = await client.post('/message', {
      text,
      userId,
      messageType,
      imageBase64,
      audioBase64,
      senderJid,
    });
    return resp.data;
  } catch (err) {
    console.error(`[coreClient] sendToApi error for ${userId}:`, err.message);
    return { reply: "I'm having a brief connection issue. Try again in a moment.", actions: [] };
  }
}

async function onboardUser(userId, phone, pushName) {
  try {
    const resp = await client.post('/onboard', { userId, phone, pushName });
    return resp.data;
  } catch (err) {
    console.error(`[coreClient] onboardUser error for ${userId}:`, err.message);
    return { messages: [], count: 0 };
  }
}

async function checkAlerts(userId) {
  try {
    const resp = await client.post('/alerts/check', { userId });
    return resp.data;
  } catch (err) {
    console.error(`[coreClient] checkAlerts error for ${userId}:`, err.message);
    return { alerts: [], count: 0 };
  }
}

async function healthCheck() {
  try {
    const resp = await client.get('/health');
    return resp.data;
  } catch (err) {
    return { status: 'error', error: err.message };
  }
}

module.exports = {
  sendToApi,
  onboardUser,
  checkAlerts,
  healthCheck,
  callCron,
  storeInboxMessage,
};

async function storeInboxMessage(userId, msg) {
  try {
    await client.post('/inbox/store', { userId, ...msg }, { timeout: 5000 });
  } catch (err) {
    // Silent — inbox storage should never block message flow
  }
}

async function callCron(path) {
  try {
    const resp = await client.post(path, {}, { timeout: 120000 });
    return resp.data;
  } catch (err) {
    console.error(`[CoreClient] Cron ${path} failed:`, err.message);
    return {};
  }
}
