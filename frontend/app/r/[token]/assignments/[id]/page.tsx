'use client';

import { AssignmentView, type PortalFrom } from '@/components/assignment-page';
import { loadStudentHome } from '@/components/student-view';

/* One assignment for the student behind this personal link, built from the
 * same /api/r/<token> payload as the course page. The back link returns to
 * the portal tab the student came from (?from=). */
export default function StudentAssignmentPage({
  params,
  searchParams
}: {
  params: { token: string; id: string };
  searchParams: { from?: string };
}) {
  const { token } = params;
  const from = portalTab(searchParams.from);
  return (
    <AssignmentView
      assignmentId={Number(params.id)}
      loader={() => loadStudentHome(token)}
      backHref={`/r/${token}${from === 'home' ? '' : `?tab=${from}`}`}
    />
  );
}

function portalTab(from: string | undefined): PortalFrom {
  return from === 'grades' || from === 'info' ? from : 'home';
}
