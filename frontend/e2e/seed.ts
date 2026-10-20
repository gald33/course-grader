import { readFileSync } from 'node:fs';
import path from 'node:path';

/* Scratch space for the smoke test's backend: database, data dir, and the
 * seed manifest written by backend/scripts/seed_e2e.py. */
export const E2E_DIR = path.join(__dirname, '..', '.e2e');
export const SEED_FILE = path.join(E2E_DIR, 'seed.json');

export type Seed = {
  course: { id: number; code: string; name: string };
  student: { name: string; team: string; token: string };
};

export function loadSeed(): Seed {
  return JSON.parse(readFileSync(SEED_FILE, 'utf8')) as Seed;
}
