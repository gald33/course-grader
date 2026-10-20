import { readFileSync } from 'node:fs';
import path from 'node:path';

/* Scratch space for the browser tests' backend: database, data dir, and the
 * seed manifest written by backend/scripts/seed_e2e.py (E2E_DIR moves it). */
export const E2E_DIR = process.env.E2E_DIR ?? path.join(__dirname, '..', '.e2e');
export const SEED_FILE = path.join(E2E_DIR, 'seed.json');

/** A student with a review link and a valid cg_student cookie value. */
export type SignedInStudent = { id: number; name: string; token: string; cookie: string };

export type Seed = {
  course: { id: number; code: string; name: string; year: number; semester: string };
  student: SignedInStudent & { team: string };
  /** The published guided lesson (fixture lesson-2) in the seeded course. */
  lesson: { id: number; slug: string; title: string; version_id: number; version_number: number };
  /** One student per lesson test that saves something, so no test sees another's progress. */
  lesson_students: Record<'trees' | 'experiments' | 'navigation' | 'insights' | 'resilience' | 'access', SignedInStudent>;
  test_student: { id: number; name: string };
};

export function loadSeed(): Seed {
  return JSON.parse(readFileSync(SEED_FILE, 'utf8')) as Seed;
}
