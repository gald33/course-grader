/* The instructor course page's sections, addressed by ?section= so other
 * pages can link back to the one they came from. */
export type CourseSection =
  | 'students'
  | 'teams'
  | 'lessons'
  | 'peer'
  | 'queue'
  | 'rubrics'
  | 'curve'
  | 'overrides'
  | 'gradebook'
  | 'settings';

export const courseSectionHref = (courseId: number, section: CourseSection) => `/course/${courseId}?section=${section}`;

/* The Lessons section's own pages: the index (no view), one lesson, the
 * course plan with its readiness table, and the private answer keys. */
export type LessonsView = 'plan' | 'keys' | number;
export const lessonsHref = (courseId: number, view?: LessonsView) =>
  view == null ? courseSectionHref(courseId, 'lessons') : `/course/${courseId}/lessons/${view}`;
