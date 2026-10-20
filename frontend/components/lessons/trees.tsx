'use client';

/* Decision trees in the lesson: the hand-written illustration (ManualTree),
 * the model actually fitted in the notebook (ActualTree, rendered from the
 * exported JSON snapshot, never from hard-coded thresholds), and the tiny
 * split illustration. Both trees use sklearn's rule — go left when
 * value <= threshold — and draw left = yes (<=), right = no (>). The diagrams
 * are pictures (aria-hidden); every interaction is a button or input, and the
 * path is also written out as text. */

import { useEffect, useMemo, useRef, useState } from 'react';

import { InlineText, Ltr, plainInline } from '@/components/lessons/inline';
import type { Block, TreeNode } from '@/components/lessons/types';

/* ---------------- Tracing (pure; checked by a standalone script) ---------------- */

export type TraceStep = {
  node: TreeNode;
  feature: string;
  threshold: number;
  value: number;
  goLeft: boolean; // value <= threshold
  next: number;
};
export type TraceResult = { steps: TraceStep[]; leaf: TreeNode };

/** The path one sample takes from `root` to a leaf. Exactly sklearn's rule:
 * X[feature] <= threshold goes to the left child, anything else to the right.
 * Throws on a broken tree (missing node, incomplete split, cycle) or a
 * missing / non-finite feature value. */
export function traceTree(nodes: TreeNode[], root: number, sample: Record<string, number>): TraceResult {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const steps: TraceStep[] = [];
  let id = root;
  for (let guard = 0; guard <= nodes.length; guard++) {
    const node = byId.get(id);
    if (!node) throw new Error(`tree node ${id} not found`);
    if (node.is_leaf) return { steps, leaf: node };
    if (node.feature == null || node.threshold == null || node.left == null || node.right == null) {
      throw new Error(`tree node ${id} is not a complete split`);
    }
    const value = sample[node.feature];
    if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error(`no value for ${node.feature}`);
    const goLeft = value <= node.threshold;
    const next = goLeft ? node.left : node.right;
    steps.push({ node, feature: node.feature, threshold: node.threshold, value, goLeft, next });
    id = next;
  }
  throw new Error('tree has a cycle');
}

/* ---------------- Layout + diagram (shared by both trees) ---------------- */

const SLOT = 150; // horizontal room per leaf, at most
const MIN_SLOT = 140; // never narrower: a box is 136px wide (days_since_purchase fills it)
const ROW = 118; // vertical distance between levels
const BOX_W = 136;
const BOX_H = 84;

type Layout = {
  byId: Map<number, TreeNode>;
  pos: Map<number, { x: number; y: number }>;
  width: number;
  height: number;
  depth: number; // max questions on one path
  leaves: number;
};

function layoutTree(nodes: TreeNode[], root: number, slot = SLOT): Layout {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const pos = new Map<number, { x: number; y: number }>();
  let leaves = 0;
  let depth = 0;
  const visit = (id: number, level: number): number => {
    const node = byId.get(id);
    if (!node || pos.has(id) || level > nodes.length) throw new Error(`broken tree at node ${id}`);
    depth = Math.max(depth, level);
    let x: number;
    if (node.is_leaf) {
      x = leaves * slot + slot / 2;
      leaves += 1;
    } else {
      if (node.left == null || node.right == null) throw new Error(`tree node ${id} is not a complete split`);
      const l = visit(node.left, level + 1);
      const r = visit(node.right, level + 1);
      x = (l + r) / 2;
    }
    pos.set(id, { x, y: level * ROW });
    return x;
  };
  visit(root, 0);
  return { byId, pos, width: leaves * slot, height: depth * ROW + BOX_H, depth, leaves };
}

type FeatureNames = (feature: string) => { he: string; en: string };

function thresholdText(t: number | null) {
  return t == null ? '' : String(t);
}

function TreeDiagram({
  nodes,
  root,
  names,
  classLabel,
  onPath,
  current,
  reached,
  showCounts,
  label,
  onOverflow
}: {
  nodes: TreeNode[];
  root: number;
  names: FeatureNames;
  classLabel: (prediction: 0 | 1) => string;
  onPath: Set<number>; // nodes on the revealed part of the path
  current: number | null; // the question being asked now
  reached: number | null; // the leaf reached, once revealed
  showCounts: boolean;
  label: string;
  onOverflow?: (wider: boolean) => void; // the picture is wider than its box
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [boxWidth, setBoxWidth] = useState<number | null>(null);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setBoxWidth(el.clientWidth);
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  // Narrow the leaf slots to fit the box (a projector's 572px fits all four
  // leaves of the learned tree), but never below one box per leaf.
  const leafCount = useMemo(() => layoutTree(nodes, root).leaves, [nodes, root]);
  const slot = boxWidth ? Math.max(MIN_SLOT, Math.min(SLOT, Math.floor(boxWidth / Math.max(1, leafCount)))) : SLOT;
  const layout = useMemo(() => layoutTree(nodes, root, slot), [nodes, root, slot]);
  const wider = boxWidth != null && layout.width > boxWidth;
  useEffect(() => {
    onOverflow?.(wider);
  }, [wider, onOverflow]);

  // When the picture is wider than the screen, keep the node that matters in
  // view: the root at first, then the question being asked or the leaf reached.
  const focusId = reached ?? current ?? root;
  const scrolledOnce = useRef(false);
  useEffect(() => {
    const el = scroller.current;
    const p = layout.pos.get(focusId);
    if (!el || !p || el.scrollWidth <= el.clientWidth) return;
    const inner = el.firstElementChild as HTMLElement | null;
    const left = (inner?.offsetLeft ?? 0) + p.x - el.clientWidth / 2;
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    el.scrollTo({ left, behavior: scrolledOnce.current && !reduce ? 'smooth' : 'auto' });
    scrolledOnce.current = true;
  }, [layout, focusId]);

  const edges: { from: TreeNode; to: number; left: boolean }[] = [];
  layout.byId.forEach((n) => {
    if (!n.is_leaf && n.left != null && n.right != null && layout.pos.has(n.id)) {
      edges.push({ from: n, to: n.left, left: true }, { from: n, to: n.right, left: false });
    }
  });

  return (
    <div className="grid min-w-0 grid-cols-1 gap-1">
      {/* relative: offsetLeft below is measured from this box, not from the page. */}
      <div
        ref={scroller}
        dir="ltr"
        role="region"
        aria-label={`${label} (אפשר לגלול לצדדים)`}
        tabIndex={0}
        className="relative overflow-x-auto rounded-md border border-line-soft bg-paper py-3"
      >
        <div className="relative mx-auto" style={{ width: layout.width, height: layout.height + 12 }} aria-hidden>
          <svg className="absolute inset-0" width={layout.width} height={layout.height + 12}>
            {edges.map((e) => {
              const a = layout.pos.get(e.from.id)!;
              const b = layout.pos.get(e.to)!;
              const lit = onPath.has(e.from.id) && onPath.has(e.to);
              return (
                <line
                  key={`${e.from.id}-${e.to}`}
                  x1={a.x}
                  y1={a.y + BOX_H + 6}
                  x2={b.x}
                  y2={b.y + 6}
                  className={lit ? 'stroke-forest' : 'stroke-ink-4'}
                  strokeWidth={lit ? 3.5 : 1.5}
                  strokeDasharray={lit ? undefined : '5 4'}
                />
              );
            })}
          </svg>
          {edges.map((e) => {
            const a = layout.pos.get(e.from.id)!;
            const b = layout.pos.get(e.to)!;
            const lit = onPath.has(e.from.id) && onPath.has(e.to);
            return (
              <span
                key={`label-${e.from.id}-${e.to}`}
                className={`absolute -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border px-1.5 text-[11px] ${
                  lit ? 'border-forest bg-forest text-paper' : 'border-border bg-card text-ink-2'
                }`}
                style={{ left: (a.x + b.x) / 2, top: (a.y + BOX_H + b.y) / 2 + 12 }}
              >
                <span dir="rtl">{e.left ? 'כן' : 'לא'}</span> {e.left ? '<=' : '>'}
              </span>
            );
          })}
          {nodes.map((n) => {
            const p = layout.pos.get(n.id);
            if (!p) return null;
            const isCurrent = current === n.id;
            const isReached = reached === n.id;
            const lit = onPath.has(n.id);
            const marker = isReached ? 'הגעתם לכאן' : isCurrent ? 'השאלה עכשיו' : lit ? 'במסלול' : null;
            return (
              <div
                key={n.id}
                dir="rtl"
                className={`absolute grid content-center rounded-md px-1.5 text-center text-[12px] leading-snug ${
                  isCurrent
                    ? 'border-2 border-terracotta bg-terracotta-tint'
                    : lit
                      ? 'border-2 border-forest bg-forest-tint'
                      : 'border border-border bg-card'
                }`}
                style={{ left: p.x - BOX_W / 2, top: p.y + 6, width: BOX_W, height: BOX_H }}
              >
                {marker ? (
                  <span
                    className={`absolute -top-2.5 left-1/2 -translate-x-1/2 whitespace-nowrap rounded-full px-1.5 text-[10px] font-semibold text-paper ${
                      isCurrent ? 'bg-terracotta' : 'bg-forest'
                    }`}
                  >
                    {marker}
                  </span>
                ) : null}
                {n.is_leaf ? (
                  <>
                    <span className="font-semibold text-ink">תחזית: {classLabel(n.prediction)}</span>
                    {showCounts && n.training_examples != null ? (
                      <span className="text-ink-2">
                        <Ltr>n={n.training_examples}</Ltr> דוגמאות
                      </span>
                    ) : null}
                    {showCounts && n.class_counts ? (
                      <span className="text-ink-2">
                        לא קנו <Ltr>{n.class_counts[0]}</Ltr> · קנו <Ltr>{n.class_counts[1]}</Ltr>
                      </span>
                    ) : null}
                  </>
                ) : (
                  <>
                    <span className="text-ink-2">
                      <InlineText text={names(n.feature ?? '').he} />
                    </span>
                    {/* Breaks only between the feature and its test, never inside "<= 13.5". */}
                    <span dir="ltr" className="font-mono text-[12px] font-semibold text-ink">
                      <span className="whitespace-nowrap">{n.feature}</span>{' '}
                      <span className="whitespace-nowrap">&lt;= {thresholdText(n.threshold)}</span>
                    </span>
                    {showCounts && n.training_examples != null ? (
                      <span className="text-[11px] text-ink-3">
                        <Ltr>n={n.training_examples}</Ltr>
                      </span>
                    ) : null}
                  </>
                )}
              </div>
            );
          })}
        </div>
      </div>
      {wider ? (
        <p className="text-[13px] text-ink-2">
          <span aria-hidden>⇆ </span>העץ רחב מהמסך – גוללים לצדדים, או פותחים ״העץ במילים״.
        </p>
      ) : null}
    </div>
  );
}

/** The whole tree in words (screen readers, and anyone who prefers text). */
function TreeOutline({
  nodes,
  root,
  names,
  classLabel,
  showCounts,
  defaultOpen = false
}: {
  nodes: TreeNode[];
  root: number;
  names: FeatureNames;
  classLabel: (prediction: 0 | 1) => string;
  showCounts: boolean;
  defaultOpen?: boolean;
}) {
  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes]);
  const render = (id: number, level: number): React.ReactNode => {
    const n = byId.get(id);
    if (!n || level > nodes.length) return null;
    if (n.is_leaf) {
      return (
        <>
          עלה – תחזית: <strong className="font-semibold">{classLabel(n.prediction)}</strong>
          {showCounts && n.training_examples != null ? (
            <>
              {' '}
              (<Ltr>{n.training_examples}</Ltr> דוגמאות אימון
              {n.class_counts ? (
                <>
                  : <Ltr>{n.class_counts[0]}</Ltr> לא קנו, <Ltr>{n.class_counts[1]}</Ltr> קנו
                </>
              ) : null}
              )
            </>
          ) : null}
        </>
      );
    }
    return (
      <>
        שאלה: <InlineText text={names(n.feature ?? '').he} /> –{' '}
        <Ltr className="font-mono text-[13px]">
          {n.feature} ≤ {thresholdText(n.threshold)}
        </Ltr>
        ?
        <ul className="mt-1 grid grid-cols-1 gap-1 border-s-2 border-line-soft ps-3">
          <li>
            <span className="font-semibold">כן (≤), שמאלה:</span> {n.left != null ? render(n.left, level + 1) : null}
          </li>
          <li>
            <span className="font-semibold">לא (&gt;), ימינה:</span> {n.right != null ? render(n.right, level + 1) : null}
          </li>
        </ul>
      </>
    );
  };
  return (
    <details open={defaultOpen || undefined} className="rounded-md border border-line-soft bg-card text-[14px]">
      <summary className="cursor-pointer px-3 py-2.5 text-ink-2">העץ במילים</summary>
      <div className="px-3 pb-2.5 leading-relaxed">{render(root, 0)}</div>
    </details>
  );
}

/** "שאלה 1: visits_30d ≤ 13.5? הערך 14: לא – ממשיכים ימינה" */
function PathList({ steps, names }: { steps: TraceStep[]; names: FeatureNames }) {
  if (!steps.length) return null;
  return (
    <ol className="grid grid-cols-1 gap-1 text-[14px]">
      {steps.map((s, i) => (
        <li key={i}>
          שאלה {i + 1}: <InlineText text={names(s.feature).he} />{' '}
          <Ltr className="font-mono text-[13px]">
            {s.feature} ≤ {thresholdText(s.threshold)}
          </Ltr>
          ? הערך <Ltr className="font-semibold">{s.value}</Ltr>: {s.goLeft ? 'כן – ממשיכים שמאלה' : 'לא – ממשיכים ימינה'}
        </li>
      ))}
    </ol>
  );
}

function compareWords(step: TraceStep) {
  return step.goLeft
    ? `${step.value} קטן מ-${thresholdText(step.threshold)} או שווה לו`
    : `${step.value} גדול מ-${thresholdText(step.threshold)}`;
}

/* ---------------- Manual (hand-written) tree ---------------- */

type ManualTreeBlock = Extract<Block, { type: 'manual_tree' }>;

const MANUAL_CLASS = (p: 0 | 1) => (p === 1 ? 'יקנה' : 'לא יקנה');

export function ManualTree({ block }: { block: ManualTreeBlock }) {
  const [customerId, setCustomerId] = useState<string | null>(null);
  const [answered, setAnswered] = useState(0); // path steps answered or revealed
  const [wrong, setWrong] = useState<'left' | 'right' | null>(null);
  const [guess, setGuess] = useState<0 | 1 | null>(null);
  const [message, setMessage] = useState('');
  const leafRef = useRef<HTMLParagraphElement>(null);

  const names: FeatureNames = (f) => ({ he: block.feature_labels[f] ?? f, en: f });
  const customer = block.customers.find((c) => c.id === customerId) ?? null;
  const { trace, depth, broken } = useMemo(() => {
    try {
      const d = layoutTree(block.nodes, block.root).depth;
      const t = customer
        ? traceTree(block.nodes, block.root, {
            visits_30d: customer.visits_30d,
            days_since_purchase: customer.days_since_purchase
          })
        : null;
      return { trace: t, depth: d, broken: false };
    } catch {
      return { trace: null, depth: 0, broken: true };
    }
  }, [block.nodes, block.root, customer]);

  const atLeaf = !!trace && answered >= trace.steps.length;
  // The branch buttons just went away (the focused one with them): continue
  // from the leaf question instead of the top of the page.
  useEffect(() => {
    if (atLeaf && guess == null && document.activeElement === document.body) leafRef.current?.focus();
  }, [atLeaf, guess]);

  if (broken) return <p className="text-[14px] text-bad">אי אפשר להציג את העץ הזה.</p>;

  const pick = (id: string) => {
    setCustomerId(id);
    setAnswered(0);
    setWrong(null);
    setGuess(null);
    setMessage('');
  };

  const step = trace && answered < trace.steps.length ? trace.steps[answered] : null;
  const onPath = new Set<number>([block.root]);
  if (trace) trace.steps.slice(0, answered).forEach((s) => onPath.add(s.next));

  const choose = (left: boolean) => {
    if (!step) return;
    if (left === step.goLeft) {
      setMessage(`נכון: ${compareWords(step)}, ולכן ${step.goLeft ? 'כן – שמאלה' : 'לא – ימינה'}.`);
      setWrong(null);
      setAnswered((a) => a + 1);
    } else {
      setWrong(left ? 'left' : 'right');
      setMessage(`לא בדיוק. בדקו שוב: האם ${step.value} קטן מ-${thresholdText(step.threshold)} או שווה לו?`);
    }
  };
  const showMe = () => {
    if (!step) return;
    setMessage(`${compareWords(step)}, ולכן ${step.goLeft ? 'כן – שמאלה' : 'לא – ימינה'}.`);
    setWrong(null);
    setAnswered((a) => a + 1);
  };
  const predict = (p: 0 | 1) => {
    if (!trace) return;
    setGuess(p);
    const truth = MANUAL_CLASS(trace.leaf.prediction);
    setMessage(p === trace.leaf.prediction ? `נכון: בעלה כתוב ״${truth}״.` : `לא בדיוק: בעלה שהגעתם אליו כתוב ״${truth}״.`);
  };

  return (
    <figure className="grid grid-cols-1 gap-3">
      {block.caption ? (
        <figcaption className="text-[14px] font-semibold text-ink-2">
          <InlineText text={block.caption} />
        </figcaption>
      ) : null}

      <div className="grid grid-cols-1 gap-2">
        <span className="text-[14px] text-ink-2">בחרו לקוח ועקבו אחריו בעץ:</span>
        <div className="flex flex-wrap gap-2">
          {block.customers.map((c) => (
            <button
              key={c.id}
              type="button"
              aria-pressed={c.id === customerId}
              onClick={() => pick(c.id)}
              className={`min-h-[44px] rounded-md border px-3 text-[14px] ${
                c.id === customerId ? 'border-forest bg-forest text-paper' : 'border-border bg-card text-ink'
              }`}
            >
              {c.id === customerId ? '✓ ' : ''}
              <InlineText text={c.label} /> · <Ltr>{c.visits_30d}</Ltr> ביקורים, <Ltr>{c.days_since_purchase}</Ltr> ימים
            </button>
          ))}
        </div>
      </div>

      <TreeDiagram
        nodes={block.nodes}
        root={block.root}
        names={names}
        classLabel={MANUAL_CLASS}
        onPath={customer ? onPath : new Set()}
        current={step ? step.node.id : null}
        reached={atLeaf && guess != null && trace ? trace.leaf.id : null}
        showCounts={false}
        label={`עץ ההמחשה${block.caption ? `: ${plainInline(block.caption)}` : ''}`}
      />

      {customer && trace ? (
        <div className="grid grid-cols-1 gap-2 rounded-md border border-border bg-card p-3">
          {step ? (
            <>
              <p className="text-[15px]">
                שאלה {answered + 1}: <InlineText text={names(step.feature).he} />{' '}
                <Ltr className="font-mono text-[14px]">
                  {step.feature} ≤ {thresholdText(step.threshold)}
                </Ltr>
                ? ל<InlineText text={customer.label} /> הערך הוא <Ltr className="font-semibold">{step.value}</Ltr>.
              </p>
              <p className="text-[15px] font-semibold">לאיזה ענף נלך?</p>
              {/* Physical order matches the drawing: yes / <= on the left. */}
              <div dir="ltr" className="grid grid-cols-2 gap-2">
                {/* Two short lines (the answer, then the direction) so a phone never breaks them mid-phrase. */}
                <button
                  type="button"
                  onClick={() => choose(true)}
                  aria-label="כן, קטן או שווה – שמאלה"
                  className={`grid min-h-[52px] place-items-center rounded-md border px-2 py-1 leading-snug ${
                    wrong === 'left' ? 'border-bad bg-bad-soft text-bad' : 'border-forest text-forest hover:bg-forest-tint'
                  }`}
                >
                  <span dir="rtl" className="text-[15px] font-semibold">
                    כן <Ltr>(≤)</Ltr>
                  </span>
                  <span className="text-[13px]">
                    <span aria-hidden>← </span>
                    <span dir="rtl">שמאלה</span>
                  </span>
                </button>
                <button
                  type="button"
                  onClick={() => choose(false)}
                  aria-label="לא, גדול – ימינה"
                  className={`grid min-h-[52px] place-items-center rounded-md border px-2 py-1 leading-snug ${
                    wrong === 'right' ? 'border-bad bg-bad-soft text-bad' : 'border-forest text-forest hover:bg-forest-tint'
                  }`}
                >
                  <span dir="rtl" className="text-[15px] font-semibold">
                    לא <Ltr>(&gt;)</Ltr>
                  </span>
                  <span className="text-[13px]">
                    <span dir="rtl">ימינה</span>
                    <span aria-hidden> →</span>
                  </span>
                </button>
              </div>
              {wrong ? (
                <button type="button" onClick={showMe} className="justify-self-start text-[14px] text-forest underline">
                  הראו לי לאן
                </button>
              ) : null}
            </>
          ) : (
            <>
              <p ref={leafRef} tabIndex={-1} className="text-[15px] font-semibold outline-none">
                הגענו לעלה. מה התחזית?
              </p>
              <div className="flex flex-wrap gap-2">
                {([1, 0] as const).map((p) => (
                  <button
                    key={p}
                    type="button"
                    aria-pressed={guess === p}
                    onClick={() => predict(p)}
                    className={`min-h-[44px] rounded-md border px-4 text-[15px] ${
                      guess === p ? 'border-forest bg-forest text-paper' : 'border-border bg-paper'
                    }`}
                  >
                    {MANUAL_CLASS(p)}
                  </button>
                ))}
              </div>
            </>
          )}
          <p aria-live="polite" className="min-h-[1.5em] text-[14px] text-ink-2">
            {message}
          </p>
          {answered > 0 ? (
            <div>
              <div className="text-[13px] font-semibold text-ink-3">המסלול עד עכשיו</div>
              <PathList steps={trace.steps.slice(0, answered)} names={names} />
            </div>
          ) : null}
          {atLeaf && guess != null ? (
            <p className="rounded-md bg-paper-2 px-3 py-2 text-[14px] leading-relaxed">
              <strong className="font-semibold">עומק העץ הזה: <Ltr>{depth}</Ltr></strong> – מספר השאלות המרבי במסלול אחד.{' '}
              <InlineText text={customer.label} /> עבר/ה {trace.steps.length === 1 ? 'שאלה אחת' : `${trace.steps.length} שאלות`} בדרך לעלה
              {trace.steps.length < depth ? ', ובכל זאת העומק הוא של המסלול הארוך ביותר בעץ.' : '.'}
            </p>
          ) : null}
          <button type="button" onClick={() => pick(customer.id)} className="justify-self-start text-[13px] text-ink-3 underline">
            להתחיל מחדש עם הלקוח הזה
          </button>
        </div>
      ) : null}

      <TreeOutline nodes={block.nodes} root={block.root} names={names} classLabel={MANUAL_CLASS} showCounts={false} />
    </figure>
  );
}

/* ---------------- The actual fitted tree (from the exported JSON) ---------------- */

type ActualTreeBlock = Extract<Block, { type: 'actual_tree' }>;

type TreeSnapshot = {
  model?: string;
  sklearn_version?: string;
  configuration?: Record<string, number | string>;
  metrics?: { train_accuracy?: number; validation_accuracy?: number; baseline_validation?: number };
  class_labels_he?: Record<string, string>;
  feature_labels_he?: Record<string, string>;
  root: number;
  nodes: TreeNode[];
};

function isSnapshot(raw: unknown): raw is TreeSnapshot {
  const t = raw as TreeSnapshot | null;
  return (
    !!t &&
    typeof t.root === 'number' &&
    Array.isArray(t.nodes) &&
    t.nodes.every((n) => typeof n?.id === 'number' && typeof n.is_leaf === 'boolean')
  );
}

// As the notebook's results table shows it — the fraction to 3 decimals
// (0.7625 → 0.762) — and that same number in percent (76.2%).
function snapshotFraction(v: number | undefined) {
  return v == null ? '—' : String(Number(v.toFixed(3)));
}
function snapshotPct(v: number | undefined) {
  return v == null ? '—' : `${+(Number(v.toFixed(3)) * 100).toFixed(1)}%`;
}

const LIMITS = { visits_30d: [0, 20], days_since_purchase: [0, 60] } as const;

export function ActualTree({ block, path, assetLabel }: { block: ActualTreeBlock; path: string | null; assetLabel?: string }) {
  const [tree, setTree] = useState<TreeSnapshot | null>(null);
  const [loadError, setLoadError] = useState(false);
  const [reload, setReload] = useState(0);
  const first = block.examples[0];
  const [visits, setVisits] = useState(first ? String(first.visits_30d) : '');
  const [days, setDays] = useState(first ? String(first.days_since_purchase) : '');
  const [shown, setShown] = useState(0); // path steps revealed so far
  const [tracing, setTracing] = useState(false);
  const [narrow, setNarrow] = useState(false); // the diagram doesn't fit: open the text version
  const restartRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    setLoadError(false);
    fetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data) => {
        if (cancelled) return;
        if (!isSnapshot(data)) throw new Error('not a tree snapshot');
        layoutTree(data.nodes, data.root); // throws on a broken tree
        setTree(data);
      })
      .catch(() => !cancelled && setLoadError(true));
    return () => {
      cancelled = true;
    };
  }, [path, reload]);

  const featureHe = tree?.feature_labels_he ?? {};
  const names: FeatureNames = (f) => ({ he: featureHe[f] ?? f, en: f });
  const classLabel = (p: 0 | 1) => tree?.class_labels_he?.[String(p)] ?? (p === 1 ? 'יקנה' : 'לא יקנה');

  const parse = (raw: string, [lo, hi]: readonly [number, number]) => {
    if (raw.trim() === '') return { value: null, error: 'הזינו מספר' };
    const v = Number(raw);
    if (!Number.isFinite(v) || !Number.isInteger(v)) return { value: null, error: 'הזינו מספר שלם' };
    if (v < lo || v > hi) return { value: null, error: `בתרגיל הטווח הוא ${lo} עד ${hi}` };
    return { value: v, error: null };
  };
  const pv = parse(visits, LIMITS.visits_30d);
  const pd = parse(days, LIMITS.days_since_purchase);
  const trace = useMemo(() => {
    if (!tree || pv.value == null || pd.value == null) return null;
    try {
      return traceTree(tree.nodes, tree.root, { visits_30d: pv.value, days_since_purchase: pd.value });
    } catch {
      return null;
    }
  }, [tree, pv.value, pd.value]);

  const restart = () => {
    setTracing(false);
    setShown(0);
  };

  const done = tracing && trace != null && shown >= trace.steps.length;
  // "כל המסלול" disappears once the leaf is reached: keep the keyboard on the next control.
  useEffect(() => {
    if (done && document.activeElement === document.body) restartRef.current?.focus();
  }, [done]);

  if (!path) return <p className="text-[14px] text-bad">קובץ העץ חסר בשיעור.</p>;
  if (loadError) {
    return (
      <div role="alert" className="rounded-md border border-bad-soft bg-card p-3 text-[14px]">
        לא הצלחנו לטעון את העץ שנלמד.{' '}
        <button type="button" className="text-forest underline" onClick={() => setReload((n) => n + 1)}>
          נסו שוב
        </button>
      </div>
    );
  }
  if (!tree) return <p className="py-6 text-center text-[14px] text-ink-3">טוען את העץ…</p>;

  const cfg = tree.configuration ?? {};
  const steps = trace ? trace.steps : [];
  const onPath = new Set<number>();
  if (tracing && trace) {
    onPath.add(tree.root);
    steps.slice(0, shown).forEach((s) => onPath.add(s.next));
  }
  const currentStep = tracing && trace && shown < steps.length ? steps[shown] : null;

  return (
    <figure className="grid grid-cols-1 gap-3">
      <div className="rounded-md border border-info-soft bg-card p-3 text-[14px]">
        <div className="flex flex-wrap items-center gap-2">
          <span className="pill pill-info font-semibold">צילום מצב של המודל</span>
          {block.caption ? (
            <figcaption className="font-semibold">
              <InlineText text={block.caption} />
            </figcaption>
          ) : null}
        </div>
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[13px] text-ink-2">
          <dt>עומק מרבי</dt>
          <dd>
            <Ltr>{String(cfg.max_depth ?? '—')}</Ltr> (<Ltr>max_depth</Ltr>)
          </dd>
          <dt>דוגמאות אימון</dt>
          <dd>
            <Ltr>{String(cfg.training_examples ?? '—')}</Ltr> (<Ltr>training_examples</Ltr>)
          </dd>
          {tree.metrics ? (
            <>
              <dt>תוצאות הריצה</dt>
              <dd>
                אימון <Ltr>{snapshotPct(tree.metrics.train_accuracy)}</Ltr> · אימות{' '}
                <Ltr>{snapshotPct(tree.metrics.validation_accuracy)}</Ltr> · קו בסיס{' '}
                <Ltr>{snapshotPct(tree.metrics.baseline_validation)}</Ltr>
              </dd>
            </>
          ) : null}
        </dl>
        <p className="mt-2 text-[13px] leading-relaxed text-ink-2">
          התמונה הזו נשמרה מהמודל שאומן בהגדרות האלה. <strong className="font-semibold">שינוי הגדרות בקולאב לא משנה אותה</strong> – כדי
          לראות עץ אחר מריצים את המחברת.
        </p>
        <details className="mt-2 rounded-md border border-line-soft bg-paper text-[13px]">
          <summary className="cursor-pointer px-3 py-2.5 text-ink-2">פרטי הריצה</summary>
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 px-3 pb-2.5 text-ink-2">
            <dt>זרעי אקראיות</dt>
            <dd>
              <Ltr>
                data_seed={String(cfg.data_seed ?? '—')}, split_seed={String(cfg.split_seed ?? '—')}, model_seed=
                {String(cfg.model_seed ?? '—')}
              </Ltr>
            </dd>
            {tree.metrics ? (
              <>
                <dt>התוצאות בקולאב</dt>
                <dd>
                  <Ltr>
                    {snapshotFraction(tree.metrics.train_accuracy)}, {snapshotFraction(tree.metrics.validation_accuracy)},{' '}
                    {snapshotFraction(tree.metrics.baseline_validation)}
                  </Ltr>
                </dd>
              </>
            ) : null}
            {tree.model ? (
              <>
                <dt>מודל</dt>
                <dd>
                  <Ltr>
                    {tree.model}
                    {tree.sklearn_version ? ` · scikit-learn ${tree.sklearn_version}` : ''}
                  </Ltr>
                </dd>
              </>
            ) : null}
          </dl>
        </details>
      </div>

      <TreeDiagram
        nodes={tree.nodes}
        root={tree.root}
        names={names}
        classLabel={classLabel}
        onPath={onPath}
        current={currentStep ? currentStep.node.id : null}
        reached={done && trace ? trace.leaf.id : null}
        showCounts
        label={assetLabel ? plainInline(assetLabel) : 'העץ שנלמד'}
        onOverflow={setNarrow}
      />
      <p className="text-[13px] text-ink-3">
        בכל עלה: התחזית, מספר דוגמאות האימון שהגיעו אליו (<Ltr>n</Ltr>), וכמה מהן לא קנו וכמה קנו.
      </p>

      <section className="grid grid-cols-1 gap-3 rounded-md border border-border bg-card p-3" aria-label="מעקב אחרי לקוח בעץ שנלמד">
        <h4 className="font-hebrew text-[16px]">מעקב אחרי לקוח</h4>
        {block.examples.length ? (
          <div className="flex flex-wrap gap-2">
            {block.examples.map((ex) => {
              const active = pv.value === ex.visits_30d && pd.value === ex.days_since_purchase;
              return (
                <button
                  key={`${ex.visits_30d}-${ex.days_since_purchase}`}
                  type="button"
                  aria-pressed={active}
                  onClick={() => {
                    setVisits(String(ex.visits_30d));
                    setDays(String(ex.days_since_purchase));
                    restart();
                  }}
                  className={`min-h-[40px] rounded-full border px-3 text-[13px] ${
                    active ? 'border-forest bg-forest-tint text-forest' : 'border-border bg-paper'
                  }`}
                >
                  {active ? '✓ ' : ''}
                  <Ltr>{ex.visits_30d}</Ltr> ביקורים, <Ltr>{ex.days_since_purchase}</Ltr> ימים
                </button>
              );
            })}
          </div>
        ) : null}
        <div className="grid grid-cols-2 gap-3">
          <TracerInput
            id={`tracer-visits-${block.asset}`}
            label={names('visits_30d').he}
            code="visits_30d"
            range={LIMITS.visits_30d}
            value={visits}
            error={pv.error}
            onChange={(v) => {
              setVisits(v);
              restart();
            }}
          />
          <TracerInput
            id={`tracer-days-${block.asset}`}
            label={names('days_since_purchase').he}
            code="days_since_purchase"
            range={LIMITS.days_since_purchase}
            value={days}
            error={pd.error}
            onChange={(v) => {
              setDays(v);
              restart();
            }}
          />
        </div>
        <div className="flex flex-wrap gap-2">
          {!tracing ? (
            <button
              type="button"
              disabled={!trace}
              onClick={() => {
                setTracing(true);
                setShown(0);
              }}
              className="h-11 rounded-md bg-forest px-4 text-[15px] font-semibold text-paper disabled:opacity-50"
            >
              מתחילים מעקב
            </button>
          ) : !done ? (
            <>
              <button
                type="button"
                onClick={() => setShown((s) => s + 1)}
                className="h-11 rounded-md bg-forest px-4 text-[15px] font-semibold text-paper"
              >
                הצעד הבא
              </button>
              <button
                type="button"
                onClick={() => setShown(steps.length)}
                className="h-11 rounded-md border border-forest px-4 text-[15px] text-forest"
              >
                כל המסלול
              </button>
            </>
          ) : (
            <button ref={restartRef} type="button" onClick={restart} className="h-11 rounded-md border border-border px-4 text-[15px]">
              לקוח אחר / מההתחלה
            </button>
          )}
        </div>
        <div aria-live="polite" className="grid grid-cols-1 gap-2">
          {tracing && currentStep ? (
            <p className="text-[14px] text-ink-2">
              השאלה הבאה: <InlineText text={names(currentStep.feature).he} />{' '}
              <Ltr className="font-mono text-[13px]">
                {currentStep.feature} ≤ {thresholdText(currentStep.threshold)}
              </Ltr>
              ? נסו לענות לבד לפני שלוחצים ״הצעד הבא״.
            </p>
          ) : null}
          {tracing ? <PathList steps={steps.slice(0, shown)} names={names} /> : null}
          {done && trace ? (
            <p className="rounded-md bg-forest-tint px-3 py-2 text-[14px] leading-relaxed">
              <strong className="font-semibold">הגענו לעלה: {classLabel(trace.leaf.prediction)}.</strong>{' '}
              {trace.leaf.training_examples != null ? (
                <>
                  הגיעו אליו <Ltr>{trace.leaf.training_examples}</Ltr> דוגמאות אימון
                  {trace.leaf.class_counts ? (
                    <>
                      : <Ltr>{trace.leaf.class_counts[0]}</Ltr> לא קנו ו-<Ltr>{trace.leaf.class_counts[1]}</Ltr> קנו
                    </>
                  ) : null}
                  .{' '}
                </>
              ) : null}
              זו ראיה מהאימון, לא הבטחה לגבי הלקוח הזה.
            </p>
          ) : null}
        </div>
      </section>

      <TreeOutline nodes={tree.nodes} root={tree.root} names={names} classLabel={classLabel} showCounts defaultOpen={narrow} />
    </figure>
  );
}

function TracerInput({
  id,
  label,
  code,
  range,
  value,
  error,
  onChange
}: {
  id: string;
  label: string;
  code: string;
  range: readonly [number, number];
  value: string;
  error: string | null;
  onChange: (v: string) => void;
}) {
  return (
    <div className="grid grid-cols-1 content-start gap-1 text-[14px]">
      <label htmlFor={id} className="font-semibold">
        <InlineText text={label} />
      </label>
      {/* The identifier and the range on their own line, each kept whole. */}
      <span id={`${id}-hint`} className="text-[12px] text-ink-2">
        <Ltr className="whitespace-nowrap font-mono">{code}</Ltr> · טווח{' '}
        <Ltr className="whitespace-nowrap">
          {range[0]}–{range[1]}
        </Ltr>
      </span>
      <input
        id={id}
        type="number"
        inputMode="numeric"
        dir="ltr"
        min={range[0]}
        max={range[1]}
        step={1}
        value={value}
        aria-invalid={!!error}
        aria-describedby={`${id}-hint${error ? ` ${id}-error` : ''}`}
        onChange={(e) => onChange(e.target.value)}
        className="h-11 w-full rounded-md border border-border bg-white px-3 text-center text-[16px]"
      />
      {error ? (
        <span id={`${id}-error`} className="text-[13px] text-bad">
          ⚠ {error}
        </span>
      ) : null}
    </div>
  );
}

/* ---------------- Split illustration ---------------- */

type SplitBlock = Extract<Block, { type: 'split_illustration' }>;

function sideSummary(points: { value: number; label: 0 | 1 }[]) {
  const no = points.filter((p) => p.label === 0).length;
  const yes = points.length - no;
  const pure = no === 0 || yes === 0;
  const prediction = no === yes ? null : yes > no ? 1 : 0;
  const errors = prediction == null ? Math.min(no, yes) : prediction === 1 ? no : yes;
  return { no, yes, pure, prediction, errors, count: points.length };
}

export function SplitIllustration({ block }: { block: SplitBlock }) {
  const [threshold, setThreshold] = useState<number | null>(null);
  const region = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(520);
  useEffect(() => {
    const el = region.current;
    if (!el) return;
    const measure = () => setW(Math.max(280, Math.min(520, el.clientWidth)));
    measure();
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const values = block.points.map((p) => p.value);
  const lo = Math.floor(Math.min(...values, ...block.candidate_thresholds)) - 1;
  const hi = Math.ceil(Math.max(...values, ...block.candidate_thresholds)) + 1;
  const PAD = 24;
  const R = W < 360 ? 7 : 8; // neighbours one apart (4 and 5) never touch
  const x = (v: number) => PAD + ((v - lo) / (hi - lo)) * (W - 2 * PAD);
  const left = threshold == null ? [] : block.points.filter((p) => p.value <= threshold);
  const right = threshold == null ? [] : block.points.filter((p) => p.value > threshold);
  const sides = threshold == null ? null : [sideSummary(left), sideSummary(right)];

  return (
    <figure className="grid grid-cols-1 gap-3">
      {block.caption ? (
        <figcaption className="text-[14px] font-semibold text-ink-2">
          <InlineText text={block.caption} />
        </figcaption>
      ) : null}
      <p className="text-[13px] text-ink-3">
        <InlineText text={block.feature_label} /> · ● קנה · ○ לא קנה
      </p>
      <div ref={region} dir="ltr" className="overflow-x-auto rounded-md border border-line-soft bg-paper" role="region" tabIndex={0} aria-label="ציר הערכים">
        <svg width={W} height={92} className="mx-auto block" aria-hidden>
          <line x1={PAD} y1={52} x2={W - PAD} y2={52} className="stroke-ink-4" strokeWidth={1.5} />
          {threshold != null ? (
            <>
              <rect x={PAD} y={14} width={x(threshold) - PAD} height={52} className="fill-forest-tint" opacity={0.7} />
              <line x1={x(threshold)} y1={8} x2={x(threshold)} y2={72} className="stroke-terracotta" strokeWidth={2.5} strokeDasharray="5 3" />
              <text x={x(threshold)} y={86} textAnchor="middle" fontSize={12} className="fill-terracotta" fontWeight={600}>
                {`<= ${threshold}`}
              </text>
            </>
          ) : null}
          {block.points.map((p, i) => (
            <g key={i}>
              <circle
                cx={x(p.value)}
                cy={38}
                r={R}
                className={p.label === 1 ? 'fill-forest stroke-forest' : 'fill-card stroke-forest'}
                strokeWidth={2}
              />
              <text x={x(p.value)} y={68} textAnchor="middle" fontSize={12} className="fill-ink-2">
                {p.value}
              </text>
            </g>
          ))}
        </svg>
      </div>
      <p className="sr-only">
        הנקודות: {block.points.map((p) => `${p.value} – ${p.label === 1 ? 'קנה' : 'לא קנה'}`).join(', ')}.
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[14px] text-ink-2">נסו סף:</span>
        {block.candidate_thresholds.map((t) => (
          <button
            key={t}
            type="button"
            aria-pressed={threshold === t}
            onClick={() => setThreshold(t)}
            className={`min-h-[40px] rounded-full border px-3 text-[14px] ${
              threshold === t ? 'border-forest bg-forest text-paper' : 'border-border bg-card'
            }`}
          >
            {threshold === t ? '✓ ' : ''}
            <Ltr>≤ {t}</Ltr>
          </button>
        ))}
      </div>
      <div aria-live="polite">
        {sides && threshold != null ? (
          <div dir="ltr" className="grid grid-cols-2 gap-2">
            {sides.map((s, i) => (
              <div key={i} dir="rtl" className="rounded-md border border-border bg-card p-2.5 text-[13px] leading-relaxed">
                <div className="font-semibold">
                  {i === 0 ? 'כן, שמאלה' : 'לא, ימינה'} (<Ltr>{i === 0 ? `≤ ${threshold}` : `> ${threshold}`}</Ltr>)
                </div>
                <div>
                  <Ltr>{s.count}</Ltr> לקוחות: <Ltr>{s.no}</Ltr> לא קנו, <Ltr>{s.yes}</Ltr> קנו
                </div>
                <div className={s.pure ? 'text-ok' : 'text-warn'}>{s.pure ? '✓ קבוצה נקייה' : '⚠ קבוצה מעורבבת'}</div>
                <div>
                  תחזית לפי הרוב:{' '}
                  {s.prediction == null ? 'תיקו – אין רוב' : s.prediction === 1 ? 'יקנה' : 'לא יקנה'}
                  {s.errors ? (
                    <>
                      {' '}
                      · טעויות: <Ltr>{s.errors}</Ltr>
                    </>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-ink-3">בחרו סף כדי לראות איך הוא מחלק את הלקוחות.</p>
        )}
      </div>
    </figure>
  );
}
