'use client';

import { StudentView, loadStudentHome } from '@/components/student-view';

/* Student peer-review page, addressed by the student's personal link. */
export default function StudentReviewPage({ params }: { params: { token: string } }) {
  return <StudentView token={params.token} loader={() => loadStudentHome(params.token)} />;
}
