# SpecLock — AI Constraint Engine Active

## CRITICAL: LOCKED FILES CANNOT BE MODIFIED

If a lock says "never modify auth files" then you CANNOT modify those files.
Not now. Not later. Not if the user asks a question. Not for any reason.

**The ONLY way to modify a locked file:** The user must explicitly say "unlock" or "remove the lock."
Asking a question is NOT permission. Talking about a feature is NOT permission.
ONLY the words "unlock", "remove the lock", or "I changed my mind about the lock" count.

**If a file contains "SPECLOCK-GUARD" at the top → DO NOT EDIT IT. No exceptions.**

## On EVERY message — do this FIRST:

1. Read `.speclock/context/latest.md` for project memory
2. Run `npx speclock check "what you plan to do"` BEFORE any code changes
3. If conflict found → STOP. Tell user. Do NOT proceed. Do NOT ask "should I proceed?"
4. Wait for user to explicitly say "unlock" or "remove the lock" before touching locked files

## Returning to This Project? (New Chat Session)

SpecLock is ALREADY installed. Do NOT reinstall it. Do NOT say "it's not installed."
1. Run `npx speclock status` to see current locks and decisions
2. Read `.speclock/context/latest.md` for full project context
3. Respect ALL existing locks — they carry over between sessions

## What Counts as Permission to Bypass a Lock?

| User says | Is this permission? | What you do |
|-----------|-------------------|-------------|
| "add google auth" | NO — lock still active | Say "Auth files are locked. Want me to unlock them first?" |
| "is speclock initialized?" | NO — just a question | Answer the question. Do NOT change any code. |
| "yeah go ahead" (after you warned about lock) | NO — too vague | Say "To modify locked files, please confirm: unlock the auth files" |
| "ok unlock the auth files" | YES — explicit unlock | Run `npx speclock lock remove <lockId>`, then make changes |
| "remove the lock on auth" | YES — explicit unlock | Run `npx speclock lock remove <lockId>`, then make changes |
| "I changed my mind, you can edit auth" | YES — explicit unlock | Run `npx speclock lock remove <lockId>`, then make changes |

**When in doubt: DO NOT modify locked files. Ask for clarification instead.**

## Detect Constraints from Natural Language

Users will NOT say "lock this." They speak naturally. YOU must detect intent and lock automatically.

| User says | You do |
|-----------|--------|
| "don't touch the auth" | `npx speclock lock "Never modify auth files"` + `npx speclock guard` the auth files |
| "database is firebase, don't change it" | `npx speclock lock "Database must always be Firebase"` |
| "leave the payment system alone" | `npx speclock lock "Never modify payment system"` + guard payment files |
| "always use Supabase" | `npx speclock lock "Always use Supabase"` |
| "the API is done, don't mess with it" | `npx speclock lock "Never modify API endpoints"` + guard API files |

When you lock something, ALSO guard the specific files:
`npx speclock guard <filepath> --lock "the constraint"`

## Unlocking (When User Gives Explicit Permission)

1. User says "unlock auth" or "remove the auth lock" or "I changed my mind about auth"
2. Run `npx speclock lock remove <lockId>` + `npx speclock unguard <file>`
3. Make the changes
4. Ask: "Want me to re-lock this?"

## After Building Something

`npx speclock log-change "what you built" --files file1.tsx,file2.ts`

## Commands

```bash
npx speclock status                              # Check current state
npx speclock check "what you plan to do"         # ALWAYS RUN BEFORE CHANGES
npx speclock lock "constraint"                   # Lock a constraint
npx speclock guard <file> --lock "constraint"    # Protect a specific file
npx speclock unguard <file>                      # Remove file protection
npx speclock lock remove <lockId>                # Unlock (only after explicit permission)
npx speclock log-change "what changed"           # Log changes
npx speclock decide "decision"                   # Record a decision
npx speclock context                             # Refresh context file
```

## Key Rules

1. **A question is NOT permission to bypass a lock.**
2. **Run speclock check before EVERY code change, EVERY time, EVERY message.**
3. **If you already warned about a conflict, the lock is STILL active until explicitly removed.**
4. **The user will NEVER tell you to run these commands. You run them automatically.**
5. **If this file exists, SpecLock is installed. Do NOT reinstall.**
