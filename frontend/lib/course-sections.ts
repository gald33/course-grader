/* The instructor course page's sections, addressed by ?section= so other
 * pages can link back to the one they came from. */
export type CourseSection =
  | 'students'
  | 'teams'
  | 'lessons'
  | 'peer'
  | 'queue'
  | 'curve'
  | 'overrides'
  | 'gradebook'
  | 'settings';

export const courseSectionHref = (courseId: number, section: CourseSection) => `/course/${courseId}?section=${section}`;
