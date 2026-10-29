// Builds eval fixtures with the app's own snapshot builder, so each one is exactly what the app would send.
import { writeFileSync, mkdirSync } from 'node:fs';
import { addDays, buildSnapshot, type HistoryInput, type WHExercise, type WHSession, type WHSet, type WHPlanVersion } from '../../../six-month-plan/supabase/functions/_shared/workout_history.ts';

const OUT = new URL('.', import.meta.url).pathname;
mkdirSync(OUT, { recursive: true });

type Log = { w: number | null; reps: number[]; rir?: number | null; pain?: boolean } | 'skip';
type Ex = WHExercise & { log: (week: number) => Log };
type Workout = { id: string; title: string; day: number; exercises: Ex[] };

const ex = (name: string, sets: number, lo: number, hi: number, weight: number | null, rest: string, log: (w: number) => Log, note = ''): Ex => ({ name, sets, reps_min: lo, reps_max: hi, weight, rest, note, log });
const flat = (w: number | null, reps: number[], rir: number | null = 2) => () => ({ w, reps, rir });
const rising = (start: number, step: number, reps: number[], rir = 2) => (week: number) => ({ w: start + step * Math.floor(week / 2), reps, rir });

interface Opts {
  name: string;
  weeks: number;
  asOf: string; // a Friday
  workouts: Workout[];
  missed?: (week: number, day: number) => boolean;
  notes?: Record<string, string>; // "week:day" → note
  bodyweight?: (dayIndex: number) => number;
  structuralChangeWeeksAgo?: number;
  reports?: HistoryInput['reports'];
}

function build(o: Opts) {
  const firstMonday = addDays(o.asOf, -4 - 7 * (o.weeks - 1));
  const sessions: WHSession[] = [];
  const sets: WHSet[] = [];
  for (let wk = 0; wk < o.weeks; wk++) {
    for (const w of o.workouts) {
      const date = addDays(firstMonday, wk * 7 + w.day - 1);
      if (date > o.asOf) continue;
      const id = `${w.id}-${wk}`;
      const missed = o.missed?.(wk, w.day) ?? false;
      sessions.push({ id, action_id: w.id, date, week_start: addDays(firstMonday, wk * 7), title: w.title, status: missed ? 'planned' : 'done', planned_minutes: 45, actual_minutes: missed ? null : 40, note: o.notes?.[`${wk}:${w.day}`] ?? '' });
      if (missed) continue;
      for (const e of w.exercises) {
        const l = e.log(wk);
        if (l === 'skip') continue;
        l.reps.forEach((r, i) => sets.push({ session_id: id, exercise: e.name, set_no: i + 1, weight: l.w, reps: r, done: true, rir: l.rir ?? null, pain: !!l.pain }));
      }
    }
  }
  const plan = (w: Workout): WHExercise[] => w.exercises.map(({ log: _l, ...e }) => e);
  const versions: WHPlanVersion[] = o.workouts.map((w) => ({ action_id: w.id, plan: plan(w), effective_on: firstMonday, source: 'backfill' }));
  if (o.structuralChangeWeeksAgo != null) {
    const on = addDays(o.asOf, -4 - 7 * o.structuralChangeWeeksAgo);
    const w = o.workouts[0]!;
    versions.unshift({ action_id: w.id, plan: [...plan(w).slice(1), { name: 'Machine Chest Press', sets: 3, reps_min: 10, reps_max: 12, weight: 50, rest: '2 min' }], effective_on: firstMonday, source: 'backfill' });
    versions.push({ action_id: w.id, plan: plan(w), effective_on: on, source: 'app', reason: 'New exercise order' });
    versions.splice(versions.findIndex((v) => v.action_id === w.id && v.source === 'backfill' && v !== versions[0]), 1);
  }
  const input: HistoryInput = {
    profile: { units: 'lb', timezone: 'America/New_York', coach_share_bodyweight: !!o.bodyweight },
    actions: o.workouts.map((w) => ({ id: w.id, title: w.title, kind: 'workout', planned_minutes: 45, archived_at: null, workout_plan: plan(w), details: 'Warm-up: band pull-aparts, feeder sets.' })),
    schedules: o.workouts.map((w) => ({ action_id: w.id, rule: 'days' as const, days: [w.day], per_week: null, effective_from: firstMonday, effective_to: null })),
    sessions,
    sets,
    planVersions: versions,
    measurementTypes: [{ id: 'bw', name: 'Weight', unit: 'lb' }],
    measurements: o.bodyweight ? Array.from({ length: o.weeks * 7 }, (_, i) => ({ type_id: 'bw', value: Math.round(o.bodyweight!(i) * 10) / 10, measured_on: addDays(firstMonday, i) })).filter((m) => m.measured_on <= o.asOf) : [],
    reports: o.reports ?? [],
  };
  const snap = buildSnapshot(input, { asOf: o.asOf, months: 6 });
  writeFileSync(`${OUT}/${o.name}.json`, JSON.stringify(snap, null, 1));
  return snap;
}

// Elliot's Mon–Fri upper-body split, trimmed to the lifts that matter for the scenarios.
function split(over: Partial<Record<string, (w: number) => Log>> = {}): Workout[] {
  const L = (name: string, f: (w: number) => Log) => over[name] ?? f;
  return [
    { id: 'mon', title: 'Mon: Chest + Back', day: 1, exercises: [
      ex('Flat DB Bench Press', 3, 8, 12, 50, '2–3 min', L('Flat DB Bench Press', rising(40, 2.5, [10, 10, 9]))),
      ex('Lat Pulldown', 4, 8, 12, 100, '2–3 min', L('Lat Pulldown', rising(90, 2.5, [10, 10, 9, 9], 1))),
      ex('Seated Lateral Raise', 3, 12, 15, 12.5, '60 sec', L('Seated Lateral Raise', (w) => ({ w: 12.5, reps: [12 + Math.min(2, Math.floor(w / 2)), 12, 12], rir: 2 }))),
    ] },
    { id: 'tue', title: 'Tue: Shoulders + Arms', day: 2, exercises: [
      ex('Seated DB Shoulder Press', 3, 8, 12, 35, '2 min', L('Seated DB Shoulder Press', rising(30, 2.5, [10, 9, 9]))),
      ex('Seated DB Curl', 3, 10, 12, 25, '90 sec', L('Seated DB Curl', rising(20, 2.5, [11, 10, 10]))),
      ex('Cable Triceps Pushdown', 3, 12, 15, 57.5, '60 sec', L('Cable Triceps Pushdown', rising(50, 2.5, [13, 13, 12]))),
    ] },
    { id: 'wed', title: 'Wed: Back + Core', day: 3, exercises: [
      ex('Seated Cable Row', 4, 6, 10, 100, '2–3 min', L('Seated Cable Row', rising(90, 2.5, [9, 8, 8, 8]))),
      ex('Hammer Strength Back Extension', 3, 10, 15, null, '90 sec', L('Hammer Strength Back Extension', flat(null, [13, 12, 12], 2))),
      ex('Sit-Up Bench Crunch (knee test)', 3, 12, 15, null, '45 sec', L('Sit-Up Bench Crunch (knee test)', flat(null, [14, 13, 12], 2)), 'First set at bodyweight: any knee pain, stop and skip it.'),
    ] },
    { id: 'thu', title: 'Thu: Chest + Shoulders', day: 4, exercises: [
      ex('Incline DB Press', 3, 8, 12, 35, '2 min', L('Incline DB Press', rising(30, 2.5, [10, 9, 9]))),
      ex('Seated Rear-Delt Fly', 3, 12, 15, 15, '60 sec', L('Seated Rear-Delt Fly', (w) => ({ w: 15, reps: [12 + Math.min(2, Math.floor(w / 2)), 12, 12], rir: 2 }))),
    ] },
    { id: 'fri', title: 'Fri: Lats + Arms', day: 5, exercises: [
      ex('Single-Arm DB Row', 3, 8, 12, 40, '90 sec', L('Single-Arm DB Row', rising(35, 2.5, [10, 10, 9]))),
      ex('Seated Hammer Curl', 3, 10, 12, 20, '60 sec', L('Seated Hammer Curl', rising(17.5, 2.5, [11, 10, 10]))),
    ] },
  ];
}

const AS_OF = '2026-11-27';
const rows: string[] = [];
const save = (o: Opts) => { const s = build(o); rows.push(`${o.name}: ${s.metrics.workouts_done_4w}/${s.metrics.workouts_planned_4w}, age ${s.program.program_age_weeks}, ${s.sessions.length} sessions`); };

// 1. Bench at the top of the range two sessions running: ready to move up.
save({ name: 'ready_to_progress', weeks: 6, asOf: AS_OF, workouts: split({ 'Flat DB Bench Press': (w) => (w >= 4 ? { w: 50, reps: [12, 12, 12], rir: 2 } : { w: 45, reps: [10, 10, 9], rir: 2 }) }) });
// 2. Two of five workouts missed for three weeks running.
save({ name: 'missed_sessions', weeks: 6, asOf: AS_OF, workouts: split(), missed: (w, d) => w >= 3 && (d === 2 || d === 4) });
// 3. Crunch hurt the knee last week, with a note.
save({ name: 'pain_note', weeks: 6, asOf: AS_OF, workouts: split({ 'Sit-Up Bench Crunch (knee test)': (w) => ({ w: null, reps: [15, 15, 15], rir: 2, pain: w >= 4 }) }), notes: { '4:3': 'Knee hurt on the crunches', '5:3': 'Knee felt off again on crunches' } });
// 4. Lat pulldown flat for 5 weeks (and the weight was already raised once).
save({ name: 'stall', weeks: 7, asOf: AS_OF, workouts: split({ 'Lat Pulldown': (w) => (w === 0 ? { w: 95, reps: [10, 10, 9, 9], rir: 1 } : { w: 100, reps: [9, 9, 8, 8], rir: 1 }) }) });
// 5. Program reshaped two weeks ago; some lifts flat since.
save({ name: 'recent_program_change', weeks: 6, asOf: AS_OF, workouts: split({ 'Lat Pulldown': flat(100, [9, 9, 8, 8], 1) }), structuralChangeWeeksAgo: 2 });
// 6. Lateral raises at the top of the range at 12.5 lb: the next dumbbell is a 40% jump.
save({ name: 'small_dumbbell', weeks: 6, asOf: AS_OF, workouts: split({ 'Seated Lateral Raise': (w) => (w >= 4 ? { w: 12.5, reps: [15, 15, 15], rir: 2 } : { w: 12.5, reps: [13, 12, 12], rir: 2 }) }) });
// 7. A plan note asking for squats (the knee rule must win).
save({ name: 'comment_conflict', weeks: 6, asOf: AS_OF, workouts: split(), notes: { '5:1': 'Feeling great. Add goblet squats next week, I want legs.' } });
// 8. Twelve weeks on the program, at a block's end, most lifts flat for 4+ weeks.
save({ name: 'block_end_stalled', weeks: 12, asOf: AS_OF, workouts: split(Object.fromEntries(['Flat DB Bench Press', 'Seated DB Shoulder Press', 'Seated DB Curl', 'Cable Triceps Pushdown', 'Seated Cable Row', 'Incline DB Press', 'Single-Arm DB Row', 'Seated Hammer Curl'].map((n) => [n, (w: number) => ({ w: w < 6 ? 30 + w * 2.5 : 45, reps: [9, 9, 8], rir: 1 })]))) });
// 9. One week of data only.
save({ name: 'too_little_data', weeks: 1, asOf: AS_OF, workouts: split() });
// 10. Losing 1.5 lb a week; lifts flat for 2 weeks (not yet a stall).
save({ name: 'cutting_holding', weeks: 6, asOf: AS_OF, workouts: split({ 'Flat DB Bench Press': (w) => ({ w: w >= 4 ? 50 : 40 + 2.5 * w, reps: [10, 10, 9], rir: 2 }) }), bodyweight: (i) => 195 - (1.5 / 7) * i });
// 11. Everything progressing mid-block.
save({ name: 'all_progressing', weeks: 6, asOf: AS_OF, workouts: split(), bodyweight: (i) => 195 - (1.4 / 7) * i });
// 12. Last week's recommendation (raise bench) wasn't applied.
save({ name: 'last_not_applied', weeks: 6, asOf: AS_OF, workouts: split({ 'Flat DB Bench Press': (w) => (w >= 3 ? { w: 50, reps: [12, 12, 12], rir: 2 } : { w: 45, reps: [10, 10, 9], rir: 2 }) }), reports: [{ id: 'r-prev', as_of: addDays(AS_OF, -7), recommendation: 'change', change_level: 2, decision: { recommendation: 'change', change_level: 2, summary: 'Bench to 55', changes: [{ workout: 'Mon: Chest + Back', type: 'load', exercise: 'Flat DB Bench Press', from: { weight: 50 }, to: { weight: 55 }, reason: 'top of range twice' }] }, user_status: null, user_note: '' }] });
console.log(rows.join('\n'));
