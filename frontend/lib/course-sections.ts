/* The instructor course page's sections, addressed by ?section= so other
 * pages can link back to the one they came from. */
export type CourseSection =
  | 'overview'
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

export const courseSectionHref = (courseId: number, section: CourseSection, tab?: string) =>
  `/course/${courseId}?section=${section}${tab ? `&tab=${encodeURIComponent(tab)}` : ''}`;
