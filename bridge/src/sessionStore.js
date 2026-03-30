const Database = require('better-sqlite3');
const path = require('path');
const crypto = require('crypto');

const DB_PATH = process.env.BRIDGE_DB || '/app/data/db/bridge.db';

let db;

function init() {
  const dir = path.dirname(DB_PATH);
  const fs = require('fs');
  fs.mkdirSync(dir, { recursive: true });

  db = new Database(DB_PATH);
  db.pragma('journal_mode = WAL');

  db.exec(`
    CREATE TABLE IF NOT EXISTS sessions (
      userId TEXT PRIMARY KEY,
      pairToken TEXT UNIQUE,
      status TEXT DEFAULT 'pending',
      phone TEXT,
      createdAt TEXT DEFAULT (datetime('now')),
      lastSeen TEXT
    )
  `);

  return db;
}

function createSession(existingUserId) {
  if (!db) init();

  const userId = existingUserId || crypto.randomUUID();
  const pairToken = crypto.randomBytes(16).toString('hex');

  const existing = db.prepare('SELECT * FROM sessions WHERE userId = ?').get(userId);
  if (existing) {
    db.prepare('UPDATE sessions SET pairToken = ?, status = ? WHERE userId = ?')
      .run(pairToken, 'pending', userId);
    return { userId, pairToken, status: 'pending' };
  }

  db.prepare('INSERT INTO sessions (userId, pairToken, status) VALUES (?, ?, ?)')
    .run(userId, pairToken, 'pending');

  return { userId, pairToken, status: 'pending' };
}

function getSession(userId) {
  if (!db) init();
  return db.prepare('SELECT * FROM sessions WHERE userId = ?').get(userId);
}

function getSessionByToken(token) {
  if (!db) init();
  return db.prepare('SELECT * FROM sessions WHERE pairToken = ?').get(token);
}

function updateSession(userId, updates) {
  if (!db) init();
  const fields = [];
  const values = [];

  for (const [key, val] of Object.entries(updates)) {
    fields.push(`${key} = ?`);
    values.push(val);
  }

  if (fields.length === 0) return;
  values.push(userId);

  db.prepare(`UPDATE sessions SET ${fields.join(', ')} WHERE userId = ?`).run(...values);
}

function getAllSessions() {
  if (!db) init();
  return db.prepare('SELECT * FROM sessions WHERE status IN (?, ?)').all('connected', 'disconnected');
}

function getSessionCount() {
  if (!db) init();
  const row = db.prepare('SELECT COUNT(*) as count FROM sessions WHERE status = ?').get('connected');
  return row ? row.count : 0;
}

// Initialize on load
init();

module.exports = {
  createSession,
  getSession,
  getSessionByToken,
  updateSession,
  getAllSessions,
  getSessionCount,
};
