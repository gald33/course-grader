'use client';

import Link from 'next/link';

import { AssignmentView, type AssignmentData } from '@/components/assignment-page';
import { apiGet } from '@/lib/api';

/* "View as student" for one assignment: the same page a student sees, from
 * the instructor preview payload of the student in ?student=. Read-only. */
export default function StudentViewAssignmentPreview({
  params,
  searchParams
}: {
  params: { id: string; assignmentId: string };
  searchParams: { student?: string; from?: string };
}) {
  const courseId = Number(params.id);
  const studentId = Number(searchParams.student);
  const tab = searchParams.from === 'grades' || searchParams.from === 'info' ? searchParams.from : null;
  const back = `/course/${courseId}/student-view?student=${studentId}${tab ? `&tab=${tab}` : ''}`;
  const banner = (
    <div dir="ltr" className="sticky top-0 z-40 border-b border-terracotta-soft bg-terracotta-tint px-4 py-2.5 text-[13px]">
      <div className="mx-auto flex max-w-[960px] flex-wrap items-center gap-x-4 gap-y-2">
        <Link href={`/course/${courseId}`} className="text-forest hover:underline">
          ← Back to course
        </Link>
        <span className="font-semibold">Student view · preview only — nothing you do here is saved</span>
      </div>
    </div>
  );
  return (
    <AssignmentView
      assignmentId={Number(params.assignmentId)}
      loader={() => apiGet<AssignmentData>(`/api/courses/${courseId}/peer/student-view/${studentId}`)}
      backHref={back}
      banner={banner}
    />
  );
}
