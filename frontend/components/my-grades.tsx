/* "My grades" card on the student page: only components the instructor has
 * released appear (the API omits the rest), with the instructor's feedback. */

/* `peer` marks a part whose score includes applied peer-review rounds. */
type Feedback = { score: number; feedback: string; peer?: true };
export type Grades = {
  hw1?: Feedback;
  hw2?: Feedback;
  project?: { code: number; report: number; bonus: number; score: number; feedback: string; peer?: true };
  talks?: { presentation: number; final_talk: number; peer?: true };
  attendance?: { percent: number | null; threshold: number; exempt: boolean; score: number };
  final?: { score: number };
};

const score = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

export function MyGradesCard({ grades }: { grades: Grades }) {
  if (!Object.keys(grades).length) return null;
  const { hw1, hw2, project, talks, attendance, final } = grades;
  return (
    <section className="mt-4 rounded-lg border border-border bg-card p-4 shadow-card">
      <h2 className="font-hebrew text-[20px]">הציונים שלי</h2>
      {final ? (
        <div className="mt-3 rounded-md bg-forest-tint px-3 py-3 text-center">
          <div className="tnum font-display text-[32px] text-forest">{score(final.score)}</div>
          <div className="text-[13px] text-ink-2">ציון סופי בקורס</div>
        </div>
      ) : null}
      <div className="mt-3 grid gap-3">
        {hw1 ? <GradeRow label="תרגיל 1" value={hw1.score} feedback={hw1.feedback} peer={hw1.peer} /> : null}
        {hw2 ? <GradeRow label="תרגיל 2" value={hw2.score} feedback={hw2.feedback} peer={hw2.peer} /> : null}
        {project ? (
          <GradeRow label="פרויקט" value={project.score} feedback={project.feedback} peer={project.peer}>
            <Detail label="קוד" value={score(project.code)} />
            <Detail label="דוח" value={score(project.report)} />
            {project.bonus ? <Detail label="בונוס" value={`+${score(project.bonus)}`} /> : null}
          </GradeRow>
        ) : null}
        {talks ? (
          <GradeRow label="הצגות" peer={talks.peer}>
            <Detail label="הצגת ביניים" value={score(talks.presentation)} />
            <Detail label="הצגה סופית" value={score(talks.final_talk)} />
          </GradeRow>
        ) : null}
        {attendance ? (
          <GradeRow label="נוכחות" value={attendance.score}>
            <Detail
              label={attendance.exempt ? 'פטור מנוכחות' : `נוכחות (נדרש ${score(attendance.threshold)}%)`}
              value={attendance.exempt || attendance.percent == null ? '—' : `${score(attendance.percent)}%`}
            />
          </GradeRow>
        ) : null}
      </div>
    </section>
  );
}

function GradeRow({
  label,
  value,
  feedback,
  peer,
  children
}: {
  label: string;
  value?: number;
  feedback?: string;
  peer?: true;
  children?: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-line-soft bg-paper px-3 py-2.5 text-[14px]">
      <div className="flex justify-between gap-2">
        <span className="font-semibold">{label}</span>
        {value != null ? <span className="tnum font-semibold">{score(value)}</span> : null}
      </div>
      {peer ? <div className="text-[12px] text-ink-3">כולל ביקורת עמיתים</div> : null}
      {children ? <div className="mt-1 grid gap-0.5 text-ink-2">{children}</div> : null}
      {feedback ? (
        <p className="mt-2 whitespace-pre-line leading-relaxed" dir="auto">
          <span className="text-ink-3">משוב מהמרצה: </span>
          {feedback}
        </p>
      ) : null}
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-2">
      <span>{label}</span>
      <span className="tnum">{value}</span>
    </div>
  );
}
