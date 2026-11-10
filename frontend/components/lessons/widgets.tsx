'use client';

/* Interactive teaching widgets for the guided lessons (lesson 3, 42052).
 * Everything runs in the browser from data in the lesson content or a static
 * JSON asset of the lesson; nothing calls a service. The tokenizer ranks
 * (o200k_base, ~1.1 MB gzipped) are a separate chunk, loaded only when a
 * live_tokenizer block mounts.
 *
 * Honesty rules, enforced here rather than left to the author: an
 * illustration always carries the "המחשה, לא מדידה" label, and measured data
 * always names its model, revision date and generation script.
 *
 * Every control is a native button, radio or range input (keyboard and
 * screen-reader operable); token and word lists also move with the arrow
 * keys. Pages are RTL; tokens, numbers and English words sit in LTR islands. */

import { useEffect, useId, useMemo, useRef, useState } from 'react';

import { InlineText, Ltr, plainInline } from '@/components/lessons/inline';
import type { LessonApi } from '@/components/lessons/lesson-player';
import type { AttentionSentence, Block, EmbeddingMapData, NeuronInput, NextWordData } from '@/components/lessons/types';

type BlockOf<T extends Block['type']> = Extract<Block, { type: T }>;

const BOX = 'grid grid-cols-1 gap-3 rounded-lg border border-info-soft bg-card p-4';
const CHIP_COLORS = ['bg-forest-soft', 'bg-terracotta-soft', 'bg-info-soft', 'bg-warn-soft', 'bg-ok-soft'];
const FOCUS = 'focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-forest';

function pct(p: number): string {
  if (p > 0 && p < 0.001) return '<0.1%';
  return `${(p * 100).toFixed(1)}%`;
}

/** The writing direction of a text, from its first strong character. */
function directionOf(text: string): 'rtl' | 'ltr' {
  const m = text.match(/[A-Za-z֐-׿]/);
  return m && /[A-Za-z]/.test(m[0]) ? 'ltr' : 'rtl';
}

function IllustrationLabel() {
  return (
    <span className="pill pill-warn justify-self-start" data-testid="illustration-label">
      המחשה, לא מדידה
    </span>
  );
}

/** Arrow keys move along a row of buttons (right/left swap in RTL). */
function arrowNav(e: React.KeyboardEvent<HTMLElement>, rtl: boolean) {
  const keys = rtl ? { next: 'ArrowLeft', prev: 'ArrowRight' } : { next: 'ArrowRight', prev: 'ArrowLeft' };
  if (![keys.next, keys.prev, 'ArrowDown', 'ArrowUp', 'Home', 'End'].includes(e.key)) return;
  const items = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('button[data-nav]'));
  const at = items.indexOf(document.activeElement as HTMLButtonElement);
  if (at < 0) return;
  e.preventDefault();
  let to = at;
  if (e.key === keys.next || e.key === 'ArrowDown') to = Math.min(items.length - 1, at + 1);
  if (e.key === keys.prev || e.key === 'ArrowUp') to = Math.max(0, at - 1);
  if (e.key === 'Home') to = 0;
  if (e.key === 'End') to = items.length - 1;
  items[to].focus();
  items[to].click();
}

function useAssetJson<T>(path: string | null, check: (d: unknown) => d is T) {
  const [data, setData] = useState<T | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (!path) return;
    let cancelled = false;
    fetch(path)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((d) => {
        if (cancelled) return;
        if (!check(d)) throw new Error('unexpected data');
        setData(d);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);
  return { data, failed };
}

function Source({ model, date, script }: { model: string; date: string; script: string }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 text-[12px] leading-relaxed text-ink-3" data-testid="measured-source">
      <p>נמדד מראש, פעם אחת, ממודל פתוח – לא מהצ׳טבוט שאתם משתמשים בו:</p>
      <p dir="ltr" className="break-all text-start font-mono">
        {model} · {date} · {script}
      </p>
    </div>
  );
}

/* =============== Live tokenizer =============== */

type Encoder = { encode: (t: string) => number[]; decode: (ids: number[]) => string };
let encoderPromise: Promise<Encoder> | null = null;
function loadO200k(): Promise<Encoder> {
  encoderPromise ??= Promise.all([import('js-tiktoken/lite'), import('js-tiktoken/ranks/o200k_base')]).then(
    ([lite, ranks]) => new lite.Tiktoken(ranks.default) as Encoder
  );
  return encoderPromise;
}

export function LiveTokenizer({ block }: { block: BlockOf<'live_tokenizer'> }) {
  const id = useId();
  const [text, setText] = useState(block.initial ?? block.examples[0] ?? '');
  const [encoder, setEncoder] = useState<Encoder | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    loadO200k()
      .then((e) => !cancelled && setEncoder(e))
      .catch(() => {
        encoderPromise = null;
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const pieces = useMemo(() => {
    if (!encoder) return null;
    return encoder.encode(text).map((t) => encoder.decode([t]));
  }, [encoder, text]);
  const dir = directionOf(text);
  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="live-tokenizer">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'מחלקים לטוקנים בזמן אמת'}
      </h4>
      <p className="text-[13px] text-ink-2">
        ה-<Ltr>tokenizer</Ltr>: <Ltr className="font-mono font-semibold">{block.encoding}</Ltr> (קוד פתוח, רץ כאן בדפדפן –
        הטקסט לא נשלח לשום מקום). הצ׳טבוט שלכם עשוי להשתמש ב-<Ltr>tokenizer</Ltr> אחר.
      </p>
      <label htmlFor={`${id}-in`} className="text-[14px] font-semibold">
        כתבו טקסט בעברית או באנגלית
      </label>
      <textarea
        id={`${id}-in`}
        dir="auto"
        rows={2}
        maxLength={500}
        value={text}
        onChange={(e) => setText(e.target.value)}
        className={`w-full rounded-md border border-border bg-paper px-3 py-2 text-[16px] ${FOCUS}`}
      />
      {block.examples.length ? (
        <div className="flex flex-wrap gap-2" role="group" aria-label="דוגמאות מוכנות">
          {block.examples.map((ex) => (
            <button
              key={ex}
              type="button"
              onClick={() => setText(ex)}
              className={`min-h-[40px] rounded-md border border-forest px-3 text-[13px] text-forest hover:bg-forest-tint ${FOCUS}`}
            >
              <bdi>{ex}</bdi>
            </button>
          ))}
        </div>
      ) : null}
      {failed ? (
        <p role="alert" className="text-[14px] text-bad">
          ה-<Ltr>tokenizer</Ltr> לא נטען. רעננו את הדף; אם זה חוזר, אפשר לראות את אותו חיתוך בסעיף 1 במחברת.
        </p>
      ) : !pieces ? (
        <p className="text-[14px] text-ink-3" role="status">
          טוען את ה-<Ltr>tokenizer</Ltr>…
        </p>
      ) : (
        <>
          <p className="text-[15px]" aria-live="polite" data-testid="token-count">
            <strong>
              <Ltr>{pieces.length}</Ltr> טוקנים
            </strong>{' '}
            · <Ltr>{[...text].length}</Ltr> תווים
          </p>
          <div dir={dir} className="flex flex-wrap gap-1" aria-label="הטוקנים, לפי הסדר" role="list">
            {pieces.map((p, i) => (
              <span
                key={i}
                role="listitem"
                className={`rounded px-1.5 py-0.5 font-mono text-[14px] ${CHIP_COLORS[i % CHIP_COLORS.length]}`}
              >
                <bdi>{p.replace(/ /g, '·').replace(/\n/g, '↵')}</bdi>
              </span>
            ))}
          </div>
          <p className="text-[12px] text-ink-3">· הוא רווח ששייך לטוקן. � הוא חלק מאות (חלק מהבתים שלה), שאי אפשר להציג לבד.</p>
        </>
      )}
    </section>
  );
}

/* =============== Guess the next word =============== */

function isNextWord(d: unknown): d is NextWordData {
  const x = d as NextWordData;
  return !!x && x.format === 1 && Array.isArray(x.prompts) && typeof x.model === 'string';
}

function Bar({ label, p, max, mark, lang }: { label: string; p: number; max: number; mark?: boolean; lang?: string }) {
  return (
    <li className="grid grid-cols-[minmax(4.5rem,auto)_1fr_auto] items-center gap-2 text-[14px]">
      <span className={`truncate ${mark ? 'font-bold text-forest' : ''}`}>
        <bdi lang={lang} className="font-mono">
          {label}
        </bdi>
        {mark ? <span className="text-[12px]"> (הניחוש שלכם)</span> : null}
      </span>
      <span className="h-3 rounded-sm bg-paper-2" aria-hidden>
        <span
          className={`block h-3 rounded-sm ${mark ? 'bg-forest' : 'bg-info'}`}
          style={{ width: `${max > 0 ? Math.max(1, (p / max) * 100) : 0}%` }}
        />
      </span>
      <Ltr className="w-14 text-end tabular-nums">{pct(p)}</Ltr>
    </li>
  );
}

export function NextWordGuess({ block, path }: { block: BlockOf<'next_word_guess'>; path: string | null }) {
  const id = useId();
  const { data, failed } = useAssetJson(path, isNextWord);
  const [promptId, setPromptId] = useState(block.prompts[0]);
  const [guess, setGuess] = useState<string | null>(null);
  const [revealed, setRevealed] = useState(false);
  const [temp, setTemp] = useState(1);
  const prompt = data?.prompts.find((p) => p.id === promptId);
  const choose = (pid: string) => {
    setPromptId(pid);
    setGuess(null);
    setRevealed(false);
    setTemp(1);
  };
  const tops = useMemo(() => {
    if (!prompt) return [];
    const weights = prompt.top_tokens.map((t) => Math.pow(t.p, 1 / temp));
    const z = weights.reduce((a, b) => a + b, 0);
    return prompt.top_tokens.map((t, i) => ({ token: t.token, p: temp === 1 ? t.p : weights[i] / z }));
  }, [prompt, temp]);

  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="next-word-guess">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'נחשו את המילה הבאה'}
      </h4>
      {failed ? (
        <p role="alert" className="text-[14px] text-bad">
          הנתונים לא נטענו. רעננו את הדף.
        </p>
      ) : !data || !prompt ? (
        <p role="status" className="text-[14px] text-ink-3">
          טוען…
        </p>
      ) : (
        <>
          <div role="group" aria-label="בחרו משפט" className="flex flex-wrap gap-2" onKeyDown={(e) => arrowNav(e, true)}>
            {block.prompts.map((pid, i) => {
              const p = data.prompts.find((x) => x.id === pid);
              if (!p) return null;
              return (
                <button
                  key={pid}
                  type="button"
                  data-nav
                  aria-pressed={pid === promptId}
                  onClick={() => choose(pid)}
                  className={`min-h-[40px] rounded-md border px-3 text-[13px] ${FOCUS} ${pid === promptId ? 'border-forest bg-forest text-paper' : 'border-border bg-paper'}`}
                >
                  משפט <Ltr>{i + 1}</Ltr>
                  {p.lang === 'en' ? ' (English)' : ''}
                </button>
              );
            })}
          </div>
          <p dir={prompt.lang === 'en' ? 'ltr' : 'rtl'} lang={prompt.lang} className="rounded-md bg-paper-2 px-3 py-2 text-[17px]" data-testid="next-word-context">
            {prompt.context} <span className="text-ink-3">…</span>
          </p>
          <fieldset className="grid grid-cols-1 gap-2" disabled={revealed}>
            <legend className="mb-1 text-[14px] font-semibold">מה לדעתכם המודל יחשב כהמשך הסביר ביותר?</legend>
            <div className="flex flex-wrap gap-2">
              {prompt.candidates.map((c) => (
                <label
                  key={c.word}
                  className={`flex min-h-[40px] cursor-pointer items-center gap-2 rounded-md border px-3 text-[15px] ${guess === c.word ? 'border-forest bg-forest-tint' : 'border-border bg-paper'}`}
                >
                  <input
                    type="radio"
                    name={`${id}-guess-${promptId}`}
                    value={c.word}
                    checked={guess === c.word}
                    onChange={() => setGuess(c.word)}
                    className={FOCUS}
                  />
                  <bdi lang={prompt.lang}>{c.word}</bdi>
                </label>
              ))}
            </div>
          </fieldset>
          {!revealed ? (
            <button
              type="button"
              disabled={!guess}
              onClick={() => setRevealed(true)}
              className={`h-11 justify-self-start rounded-md bg-forest px-5 text-[15px] font-semibold text-paper disabled:opacity-50 ${FOCUS}`}
            >
              {guess ? 'הצגת ההסתברויות של המודל' : 'בחרו ניחוש קודם'}
            </button>
          ) : (
            <div className="grid grid-cols-1 gap-3" aria-live="polite" data-testid="next-word-result">
              <div>
                <p className="mb-1 text-[14px] font-semibold">החלק של כל מילה, מתוך ארבע האפשרויות בלבד</p>
                <ul className="grid grid-cols-1 gap-1">
                  {[...prompt.candidates]
                    .sort((a, b) => b.share - a.share)
                    .map((c) => (
                      <Bar key={c.word} label={c.word} p={c.share} max={1} mark={c.word === guess} lang={prompt.lang} />
                    ))}
                </ul>
              </div>
              <div>
                <p className="mb-1 text-[14px] font-semibold">10 הטוקנים הבאים הסבירים ביותר (מכל אוצר הטוקנים)</p>
                <ul className="grid grid-cols-1 gap-1" data-testid="top-tokens">
                  {tops.map((t, i) => (
                    <Bar key={i} label={t.token.replace(/ /g, '·').replace(/\n/g, '↵') || '∅'} p={t.p} max={tops[0]?.p ?? 1} lang={prompt.lang} />
                  ))}
                </ul>
                {temp === 1 ? (
                  <p className="mt-1 text-[12px] text-ink-3">
                    כל שאר הטוקנים יחד: <Ltr>{pct(prompt.other_p)}</Ltr>. · הוא רווח בתחילת הטוקן. בעברית רבים מהם חלקי מילים.
                  </p>
                ) : null}
              </div>
              {block.temperature ? (
                <div className="grid grid-cols-1 gap-1 rounded-md border border-line-soft p-3">
                  <label htmlFor={`${id}-temp`} className="text-[14px] font-semibold">
                    טמפרטורה: <Ltr>{temp.toFixed(1)}</Ltr>
                  </label>
                  <input
                    id={`${id}-temp`}
                    type="range"
                    dir="ltr"
                    min={0.2}
                    max={2}
                    step={0.1}
                    value={temp}
                    onChange={(e) => setTemp(Number(e.target.value))}
                    className={FOCUS}
                  />
                  <p className="text-[12px] text-ink-3">
                    המחשה: הטמפרטורה מחלקת מחדש רק את 10 הטוקנים שנשמרו (נמוכה – הבחירה חדה יותר; גבוהה – שטוחה יותר). המודל
                    לא רץ מחדש.
                  </p>
                </div>
              ) : null}
              <button
                type="button"
                onClick={() => {
                  setRevealed(false);
                  setGuess(null);
                  setTemp(1);
                }}
                className={`justify-self-start text-[14px] font-semibold text-forest underline ${FOCUS}`}
              >
                לנחש שוב
              </button>
            </div>
          )}
          <Source model={data.model} date={data.generated_at} script={data.script} />
        </>
      )}
    </section>
  );
}

/* =============== Click-to-see attention =============== */

function SentenceAttention({ sentence }: { sentence: AttentionSentence }) {
  const [sel, setSel] = useState(sentence.start ?? sentence.tokens.length - 1);
  useEffect(() => setSel(sentence.start ?? sentence.tokens.length - 1), [sentence]);
  const row = sentence.weights[sel] ?? [];
  const max = Math.max(...row, 0.0001);
  const ranked = row
    .map((w, j) => ({ w, j }))
    .filter((x) => x.w > 0 && x.j !== sel)
    .sort((a, b) => b.w - a.w)
    .slice(0, 3);
  return (
    <div className="grid grid-cols-1 gap-2">
      {sentence.label ? (
        <p className="text-[14px] font-semibold">
          <InlineText text={sentence.label} />
        </p>
      ) : null}
      <div
        role="group"
        aria-label="בחרו מילה כדי לראות על אילו מילים היא נשענת"
        className="flex flex-wrap gap-1.5"
        onKeyDown={(e) => arrowNav(e, true)}
        data-testid={`attention-${sentence.id}`}
      >
        {sentence.tokens.map((t, j) => {
          const w = row[j] ?? 0;
          const later = j > sel;
          const strength = later ? 0 : w / max;
          return (
            <button
              key={j}
              type="button"
              data-nav
              aria-pressed={j === sel}
              aria-label={`${t}${j === sel ? ' (נבחרה)' : later ? '' : `, משקל ${Math.round(w * 100)}%`}`}
              onClick={() => setSel(j)}
              className={`grid min-h-[44px] min-w-[44px] content-center justify-items-center rounded-md border px-2 py-1 text-[16px] ${FOCUS} ${j === sel ? 'border-forest ring-2 ring-forest' : 'border-border'} ${later ? 'text-ink-4' : ''}`}
              style={{ backgroundColor: later ? undefined : `rgba(45, 93, 79, ${(0.08 + strength * 0.6).toFixed(2)})` }}
              data-weight={later ? '' : w.toFixed(2)}
            >
              <bdi>{t}</bdi>
              <Ltr className="text-[11px] tabular-nums">{later ? '—' : `${Math.round(w * 100)}%`}</Ltr>
            </button>
          );
        })}
      </div>
      <p className="text-[14px]" aria-live="polite" data-testid="attention-summary">
        «<bdi>{sentence.tokens[sel]}</bdi>» נשענת בעיקר על:{' '}
        {ranked.length
          ? ranked.map((x, i) => (
              <span key={x.j}>
                {i ? ', ' : ''}«<bdi>{sentence.tokens[x.j]}</bdi>» (<Ltr>{Math.round(x.w * 100)}%</Ltr>)
              </span>
            ))
          : 'רק על עצמה (זו המילה הראשונה)'}
        . מילים שאחריה מסומנות ב-—, כי המודל מסתכל רק אחורה.
      </p>
    </div>
  );
}

export function AttentionView({ block }: { block: BlockOf<'attention_view'> }) {
  const id = useId();
  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="attention-view">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'לחצו על מילה: על מה היא מסתכלת?'}
      </h4>
      <IllustrationLabel />
      <p className="text-[12px] text-ink-3">
        המשקלים נבחרו ביד כדי להמחיש את הרעיון. הם לא נמדדו מתוך מודל כלשהו, ובטח לא מתוך הצ׳טבוט שלכם.
      </p>
      {block.sentences.map((s) => (
        <SentenceAttention key={s.id} sentence={s} />
      ))}
    </section>
  );
}

/* =============== One neuron =============== */

function fmt(n: number): string {
  return (Math.round(n * 100) / 100).toString().replace('-', '−');
}

export function NeuronPlayground({ block }: { block: BlockOf<'neuron_playground'> }) {
  const id = useId();
  const [values, setValues] = useState(() => block.inputs.map((i) => i.value));
  const [weights, setWeights] = useState(() => block.inputs.map((i) => i.weight));
  const [bias, setBias] = useState(block.bias);
  const z = values.reduce((acc, v, i) => acc + v * weights[i], bias);
  const out = block.activation === 'sigmoid' ? 1 / (1 + Math.exp(-z)) : z >= 0 ? 1 : 0;
  const on = block.activation === 'sigmoid' ? out >= 0.5 : out === 1;
  const slider = (key: string, label: React.ReactNode, value: number, min: number, max: number, step: number, set: (v: number) => void) => (
    <div className="grid grid-cols-1 gap-1">
      <label htmlFor={`${id}-${key}`} className="flex justify-between gap-2 text-[14px]">
        <span>{label}</span>
        <Ltr className="font-mono tabular-nums">{fmt(value)}</Ltr>
      </label>
      <input id={`${id}-${key}`} type="range" dir="ltr" min={min} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))} className={FOCUS} />
    </div>
  );
  const update = (arr: number[], i: number, v: number) => arr.map((x, j) => (j === i ? v : x));
  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="neuron-playground">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'נוירון אחד'}
      </h4>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div className="grid grid-cols-1 gap-2 rounded-md bg-paper-2 p-3">
          <p className="text-[13px] font-semibold">הקלטים (מה ידוע)</p>
          {block.inputs.map((inp: NeuronInput, i) =>
            slider(`in-${inp.key}`, <InlineText text={inp.label} />, values[i], inp.min, inp.max, inp.step, (v) => setValues(update(values, i, v)))
          )}
        </div>
        <div className="grid grid-cols-1 gap-2 rounded-md bg-paper-2 p-3">
          <p className="text-[13px] font-semibold">המשקלים וההטיה (מה שהאימון היה מכוונן)</p>
          {block.inputs.map((inp, i) =>
            slider(
              `w-${inp.key}`,
              <>
                משקל של <InlineText text={inp.label} />
              </>,
              weights[i],
              block.weight_range[0],
              block.weight_range[1],
              0.1,
              (v) => setWeights(update(weights, i, v))
            )
          )}
          {slider('bias', 'הטיה (bias)', bias, block.bias_range[0], block.bias_range[1], 0.1, setBias)}
        </div>
      </div>
      <p className="overflow-x-auto rounded-md bg-paper px-3 py-2 text-[13px]" dir="ltr" data-testid="neuron-sum">
        <span className="font-mono">
          z = {block.inputs.map((_, i) => `${fmt(weights[i])}×${fmt(values[i])}`).join(' + ')} + {fmt(bias)} = <b>{fmt(z)}</b>
        </span>
      </p>
      <p
        aria-live="polite"
        data-testid="neuron-output"
        data-on={on ? '1' : '0'}
        className={`rounded-md px-3 py-2 text-[16px] font-semibold ${on ? 'bg-forest text-paper' : 'bg-warn-soft text-ink'}`}
      >
        {block.activation === 'sigmoid' ? (
          <>
            פלט: <Ltr>{pct(out)}</Ltr> –{' '}
          </>
        ) : (
          <>
            הסכום {z >= 0 ? 'עבר' : 'לא עבר'} את הסף 0 –{' '}
          </>
        )}
        <InlineText text={block.output_labels[on ? 1 : 0]} />
      </p>
    </section>
  );
}

/* =============== A tiny classifier learning =============== */

function lossAndGrad(points: BlockOf<'training_demo'>['points'], w: [number, number, number], scale: (p: { x: number; y: number }) => [number, number]) {
  let loss = 0;
  let errors = 0;
  const g: [number, number, number] = [0, 0, 0];
  for (const pt of points) {
    const [x, y] = scale(pt);
    const z = w[0] * x + w[1] * y + w[2];
    const p = 1 / (1 + Math.exp(-z));
    const e = Math.min(1 - 1e-9, Math.max(1e-9, p));
    loss -= pt.label ? Math.log(e) : Math.log(1 - e);
    if ((p >= 0.5 ? 1 : 0) !== pt.label) errors += 1;
    g[0] += (p - pt.label) * x;
    g[1] += (p - pt.label) * y;
    g[2] += p - pt.label;
  }
  const n = points.length;
  return { loss: loss / n, errors, grad: g.map((v) => v / n) as [number, number, number] };
}

export function TrainingDemo({ block }: { block: BlockOf<'training_demo'> }) {
  const id = useId();
  const [w, setW] = useState<[number, number, number]>(block.start);
  const [steps, setSteps] = useState(0);
  const xs = block.points.map((p) => p.x);
  const ys = block.points.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const scale = (p: { x: number; y: number }): [number, number] => [(p.x - x0) / (x1 - x0 || 1), (p.y - y0) / (y1 - y0 || 1)];
  const now = lossAndGrad(block.points, w, scale);
  const step = (k: number) => {
    let cur = w;
    for (let i = 0; i < k; i += 1) {
      const { grad } = lossAndGrad(block.points, cur, scale);
      cur = [cur[0] - block.learning_rate * grad[0], cur[1] - block.learning_rate * grad[1], cur[2] - block.learning_rate * grad[2]];
    }
    setW(cur);
    setSteps((s) => s + k);
  };
  // Drawing: unit square, 0..1, padded; y up.
  const S = 300;
  const P = 16;
  const toPx = (ux: number, uy: number) => [P + ux * (S - 2 * P), S - P - uy * (S - 2 * P)];
  // The boundary w0*x + w1*y + w2 = 0, clipped to the unit square.
  const line = (() => {
    const pts: [number, number][] = [];
    const [a, b, c] = w;
    for (const ux of [0, 1]) if (Math.abs(b) > 1e-9) pts.push([ux, -(a * ux + c) / b]);
    for (const uy of [0, 1]) if (Math.abs(a) > 1e-9) pts.push([-(b * uy + c) / a, uy]);
    const inside = pts.filter(([ux, uy]) => ux >= -1e-9 && ux <= 1 + 1e-9 && uy >= -1e-9 && uy <= 1 + 1e-9);
    return inside.length >= 2 ? [inside[0], inside[inside.length - 1]] : null;
  })();
  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="training-demo">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'מודל קטן לומד'}
      </h4>
      <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-[minmax(0,320px)_1fr]">
        <svg viewBox={`0 0 ${S} ${S}`} className="w-full max-w-[320px] rounded-md border border-line-soft bg-paper" role="img" aria-label={`נקודות האימון וקו ההחלטה אחרי ${steps} צעדים`}>
          {line ? (
            <line
              x1={toPx(line[0][0], line[0][1])[0]}
              y1={toPx(line[0][0], line[0][1])[1]}
              x2={toPx(line[1][0], line[1][1])[0]}
              y2={toPx(line[1][0], line[1][1])[1]}
              stroke="#fafafa"
              strokeWidth={2}
              strokeDasharray="6 4"
              data-testid="boundary"
            />
          ) : null}
          {block.points.map((pt, i) => {
            const [cx, cy] = toPx(...scale(pt));
            return pt.label ? (
              <circle key={i} cx={cx} cy={cy} r={6} fill="#34d399" />
            ) : (
              <rect key={i} x={cx - 5.5} y={cy - 5.5} width={11} height={11} fill="#fb923c" />
            );
          })}
        </svg>
        <div className="grid grid-cols-1 gap-2 text-[14px]">
          <p>
            <span aria-hidden className="inline-block h-3 w-3 rounded-full bg-forest align-middle" /> <InlineText text={block.class_labels[1]} /> ·{' '}
            <span aria-hidden className="inline-block h-3 w-3 bg-terracotta align-middle" /> <InlineText text={block.class_labels[0]} />
          </p>
          <p className="text-[13px] text-ink-2">
            ציר אופקי: <InlineText text={block.x_label} /> · ציר אנכי: <InlineText text={block.y_label} />
          </p>
          <p aria-live="polite" data-testid="training-status">
            צעדי אימון: <Ltr>{steps}</Ltr> · טעויות: <Ltr>{now.errors}</Ltr> מתוך <Ltr>{block.points.length}</Ltr> · שגיאה ממוצעת (<Ltr>loss</Ltr>):{' '}
            <Ltr className="tabular-nums">{now.loss.toFixed(3)}</Ltr>
          </p>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={() => step(1)} className={`h-11 rounded-md bg-forest px-4 font-semibold text-paper ${FOCUS}`}>
              צעד אימון אחד
            </button>
            <button type="button" onClick={() => step(10)} className={`h-11 rounded-md border border-forest px-4 font-semibold text-forest ${FOCUS}`}>
              10 צעדים
            </button>
            <button
              type="button"
              onClick={() => {
                setW(block.start);
                setSteps(0);
              }}
              className={`h-11 rounded-md px-3 text-forest underline ${FOCUS}`}
            >
              איפוס
            </button>
          </div>
          <p className="text-[12px] text-ink-3">
            כל צעד מזיז מעט את המשקלים בכיוון שמקטין את השגיאה על הדוגמאות. אותו חישוב בכל פעם – בלי אקראיות.
          </p>
        </div>
      </div>
    </section>
  );
}

/* =============== Embedding map =============== */

function isMap(d: unknown): d is EmbeddingMapData {
  const x = d as EmbeddingMapData;
  return !!x && x.format === 1 && Array.isArray(x.words) && typeof x.model === 'string';
}

const GROUP_COLORS: Record<string, string> = {
  bakery: '#fb923c',
  drinks: '#7dd3fc',
  days: '#fcd34d',
  feelings: '#fda4af',
  people: '#34d399'
};
// Where each neighbour's rank number sits around its dot (1..5), so close dots don't merge their numbers.
const RANK_OFFSETS: [number, number][] = [
  [9, -5],
  [-9, -5],
  [9, 12],
  [-9, 12],
  [0, -11]
];
const GROUP_HE: Record<string, string> = { bakery: 'מאפייה', drinks: 'משקאות', days: 'ימים', feelings: 'רגשות', people: 'אנשים' };

export function EmbeddingMap({ block, path }: { block: BlockOf<'embedding_map'>; path: string | null }) {
  const id = useId();
  const { data, failed } = useAssetJson(path, isMap);
  const [sel, setSel] = useState<string | null>(block.start ?? null);
  const byId = useMemo(() => new Map((data?.words ?? []).map((w) => [w.id, w])), [data]);
  const selected = sel ? byId.get(sel) : undefined;
  const near = new Set(selected?.neighbors.map((n) => n.id) ?? []);
  const S = 320;
  const P = 26;
  const px = (w: { x: number; y: number }) => [P + w.x * (S - 2 * P), S - P - w.y * (S - 2 * P)];
  // The selected word's label grows inward near an edge, so it is never
  // clipped; neighbours carry their rank (1-5), named in the list beside.
  const anchorFor = (w: { x: number; lang: string }): 'start' | 'middle' | 'end' => {
    const inward = w.x < 0.2 ? 'right' : w.x > 0.8 ? 'left' : null;
    if (!inward) return 'middle';
    const rtl = w.lang === 'he';
    return inward === 'right' ? (rtl ? 'end' : 'start') : rtl ? 'start' : 'end';
  };
  const rankOf = (wid: string) => (selected?.neighbors.findIndex((n) => n.id === wid) ?? -1) + 1;
  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="embedding-map">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'מפת ייצוגים'}
      </h4>
      {failed ? (
        <p role="alert" className="text-[14px] text-bad">
          המפה לא נטענה. רעננו את הדף.
        </p>
      ) : !data ? (
        <p role="status" className="text-[14px] text-ink-3">
          טוען…
        </p>
      ) : (
        <>
          <p className="text-[13px] text-ink-2">
            <strong>
              הטלה ל-<Ltr>2</Ltr> ממדים: מרחקים משוערים.
            </strong>{' '}
            לכל מילה יש <Ltr>{data.dimensions}</Ltr> מספרים; המפה דוחסת אותם לשניים (<Ltr>PCA</Ltr>, שומרת כ-
            <Ltr>{Math.round(data.explained_variance_2d * 100)}%</Ltr> מהשונות), ולכן מילים יכולות להיראות קרובות או רחוקות יותר מכפי שהן.
            השכנים ברשימה מחושבים במלוא <Ltr>{data.dimensions}</Ltr> הממדים.
          </p>
          <div className="grid grid-cols-1 items-start gap-3 md:grid-cols-[minmax(0,340px)_1fr]">
            <svg viewBox={`0 0 ${S} ${S}`} className="w-full max-w-[340px] rounded-md border border-line-soft bg-paper" role="img" aria-label="מפת המילים בשני ממדים">
              {selected
                ? selected.neighbors.map((n) => {
                    const o = byId.get(n.id);
                    if (!o) return null;
                    const [ax, ay] = px(selected);
                    const [bx, by] = px(o);
                    return <line key={n.id} x1={ax} y1={ay} x2={bx} y2={by} stroke="#fafafa" strokeOpacity={0.35} />;
                  })
                : null}
              {data.words.map((w) => {
                const [cx, cy] = px(w);
                const on = w.id === sel;
                const lit = near.has(w.id);
                return (
                  <g key={w.id} opacity={sel && !on && !lit ? 0.35 : 1}>
                    <circle cx={cx} cy={cy} r={on ? 7 : 4.5} fill={GROUP_COLORS[w.group] ?? '#8e8e96'} stroke={on ? '#fafafa' : 'none'} strokeWidth={2} />
                    {on ? (
                      <text
                        x={cx}
                        y={cy - 11}
                        fontSize={12}
                        fontWeight={700}
                        textAnchor={anchorFor(w)}
                        fill="#fafafa"
                        stroke="#09090b"
                        strokeWidth={3}
                        paintOrder="stroke"
                        direction={w.lang === 'he' ? 'rtl' : 'ltr'}
                      >
                        {w.text}
                      </text>
                    ) : lit ? (
                      // A neighbour shows its rank; the numbered list beside the map names it.
                      <text
                        x={cx + RANK_OFFSETS[(rankOf(w.id) - 1 + 5) % 5][0]}
                        y={cy + RANK_OFFSETS[(rankOf(w.id) - 1 + 5) % 5][1]}
                        fontSize={10}
                        textAnchor="middle"
                        fill="#fafafa"
                        stroke="#09090b"
                        strokeWidth={3}
                        paintOrder="stroke"
                      >
                        {rankOf(w.id)}
                      </text>
                    ) : null}
                  </g>
                );
              })}
            </svg>
            <div className="grid grid-cols-1 gap-2">
              <div aria-live="polite" data-testid="embedding-neighbors" className="rounded-md bg-paper-2 p-3 text-[14px]">
                {selected ? (
                  <>
                    <p className="font-semibold">
                      5 השכנים הקרובים ל«<bdi lang={selected.lang}>{selected.text}</bdi>» (דמיון קוסינוס במלוא הממדים):
                    </p>
                    <ol className="list-decimal ps-6">
                      {selected.neighbors.map((n) => (
                        <li key={n.id}>
                          <bdi lang={byId.get(n.id)?.lang}>{byId.get(n.id)?.text}</bdi> – <Ltr className="tabular-nums">{n.cosine.toFixed(2)}</Ltr>
                        </li>
                      ))}
                    </ol>
                  </>
                ) : (
                  <p>בחרו מילה כדי לראות את השכנים שלה.</p>
                )}
              </div>
              <div role="group" aria-label="המילים במפה" className="flex flex-wrap gap-1.5" onKeyDown={(e) => arrowNav(e, true)}>
                {data.words.map((w) => (
                  <button
                    key={w.id}
                    type="button"
                    data-nav
                    aria-pressed={w.id === sel}
                    onClick={() => setSel(w.id)}
                    className={`min-h-[36px] rounded-md border px-2 text-[13px] ${FOCUS} ${w.id === sel ? 'border-forest bg-forest text-paper' : near.has(w.id) ? 'border-forest bg-forest-tint' : 'border-border bg-paper'}`}
                  >
                    <span aria-hidden className="me-1 inline-block h-2 w-2 rounded-full align-middle" style={{ backgroundColor: GROUP_COLORS[w.group] }} />
                    <bdi lang={w.lang}>{w.text}</bdi>
                  </button>
                ))}
              </div>
              <p className="text-[12px] text-ink-3">
                <span className="me-2">הצבעים: נושא שקבענו ביד –</span>
                {Object.entries(GROUP_HE).map(([g, he]) => (
                  <span key={g} className="me-3 whitespace-nowrap">
                    <span aria-hidden className="me-1 inline-block h-2 w-2 rounded-full align-middle" style={{ backgroundColor: GROUP_COLORS[g] }} />
                    {he}
                  </span>
                ))}
              </p>
            </div>
          </div>
          <Source model={data.model} date={data.generated_at} script={data.script} />
        </>
      )}
    </section>
  );
}

/* =============== Image =============== */

export function ImageBlockView({ block, path }: { block: BlockOf<'image'>; path: string | null }) {
  if (!path) return <p className="text-[14px] text-bad">התמונה חסרה בשיעור.</p>;
  return (
    <figure className="grid grid-cols-1 gap-2">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={path} alt={block.alt} className="h-auto w-full max-w-[720px] rounded-md border border-line-soft bg-card" />
      {block.caption ? (
        <figcaption className="text-[13px] text-ink-2">
          <InlineText text={block.caption} />
        </figcaption>
      ) : null}
    </figure>
  );
}

/* =============== Architecture map (a self-check) =============== */

/** Sort the product's pieces into parts with native selects (keyboard and
 * screen-reader operable, no dragging). The lesson's own mapping, with one
 * reason per item, appears only after "השוו לגרסה שלנו" is pressed, and hides
 * again on request. Nothing is sent or saved: it is practice, not a check. */
export function ArchitectureMap({ block }: { block: BlockOf<'architecture_map'> }) {
  const id = useId();
  const [picks, setPicks] = useState<Record<string, string>>({});
  const [shown, setShown] = useState(false);
  const partLabel = (pid: string) => block.parts.find((p) => p.id === pid)?.label ?? pid;
  const chosen = block.items.filter((i) => picks[i.id]).length;
  const matching = block.items.filter((i) => picks[i.id] === i.model_part).length;
  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="architecture-map">
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'מפת ארכיטקטורה'}
      </h4>
      <p id={`${id}-help`} className="text-[13px] text-ink-2">
        לכל פריט, בחרו מהרשימה את החלק שעושה אותו. אפשר לעבור בין הרשימות במקש <Ltr>Tab</Ltr> ולבחור בחיצים.
      </p>
      <fieldset className="grid grid-cols-1 gap-2" aria-describedby={`${id}-help`}>
        <legend className="sr-only">שיוך כל פריט לחלק במוצר</legend>
        <ul className="grid grid-cols-1 gap-2">
          {block.items.map((item) => {
            const pick = picks[item.id] ?? '';
            const same = pick === item.model_part;
            return (
              <li key={item.id} className="grid grid-cols-1 gap-2 rounded-md bg-paper-2 p-3 md:grid-cols-[minmax(0,1fr)_minmax(0,16rem)] md:items-center" data-testid={`arch-item-${item.id}`}>
                <label htmlFor={`${id}-${item.id}`} className="text-[15px] font-semibold">
                  <InlineText text={item.label} />
                </label>
                <select
                  id={`${id}-${item.id}`}
                  value={pick}
                  onChange={(e) => setPicks({ ...picks, [item.id]: e.target.value })}
                  className={`min-h-[44px] w-full min-w-0 rounded-md border border-border bg-card px-2 text-[15px] ${FOCUS}`}
                >
                  <option value="">בחרו חלק…</option>
                  {block.parts.map((p) => (
                    <option key={p.id} value={p.id}>
                      {plainInline(p.label)}
                    </option>
                  ))}
                </select>
                {shown ? (
                  <p className="text-[14px] leading-relaxed md:col-span-2" data-testid="arch-model">
                    <span className={`pill ${pick ? (same ? 'pill-ok' : 'pill-warn') : ''} me-2`}>
                      {pick ? (same ? '✓ כמו אצלנו' : '≠ אצלנו אחרת') : 'לא בחרתם'}
                    </span>
                    <b>
                      אצלנו: <InlineText text={partLabel(item.model_part)} />.
                    </b>{' '}
                    <InlineText text={item.reason} />
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
      </fieldset>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-expanded={shown}
          aria-controls={`${id}-result`}
          onClick={() => setShown(!shown)}
          className={`min-h-[44px] rounded-md border border-forest px-4 font-semibold text-forest ${FOCUS}`}
        >
          {shown ? 'הסתרת הגרסה שלנו' : 'השוו לגרסה שלנו'}
        </button>
        <span className="text-[13px] text-ink-3">
          בחרתם <Ltr>{chosen}</Ltr> מתוך <Ltr>{block.items.length}</Ltr>. תרגול בלבד: שום דבר לא נשמר ולא נבדק.
        </span>
      </div>
      <p id={`${id}-result`} aria-live="polite" className="text-[14px]" data-testid="arch-summary">
        {shown ? (
          <>
            <Ltr>{matching}</Ltr> מתוך <Ltr>{block.items.length}</Ltr> כמו בגרסה שלנו. הבדל אינו בהכרח טעות – בדקו את הנימוק.
          </>
        ) : null}
      </p>
    </section>
  );
}

/* ---------------- Agent turn stepper (lesson 4) ---------------- */

/** One illustrative coding-agent turn, frame by frame: context, model
 * output, the harness's action and the tool result. Before each next frame
 * the student predicts what happens; the reveal follows. Predictions are not
 * keyed or saved. Reaching the last frame records `done_ack` (the step's
 * "walked the whole turn" ack), which can't be ticked by hand.
 *
 * Keyboard: native buttons and radios; arrow keys move between frames (RTL:
 * left is next) unless focus is in the prediction choices. Whenever the
 * focused control disables itself or unmounts, focus moves to the new
 * frame's heading or to the first prediction choice, never to <body>. */
export function AgentTurnStepper({ block, api }: { block: BlockOf<'agent_turn_stepper'>; api: LessonApi }) {
  const id = useId();
  const frames = block.frames;
  const [at, setAt] = useState(0);
  const [predicting, setPredicting] = useState(false);
  const [choice, setChoice] = useState('');
  const [picks, setPicks] = useState<Record<string, string>>({});
  // Where focus goes after the next render: the frame heading or the first choice.
  const [focusTo, setFocusTo] = useState<'frame' | 'predict' | null>(null);
  const frameHeading = useRef<HTMLHeadingElement>(null);
  const firstChoice = useRef<HTMLInputElement>(null);
  const frame = frames[at];
  const next = frames[at + 1];
  const last = at === frames.length - 1;
  const doneAck = block.done_ack;
  const done = !!doneAck && api.acked(doneAck);

  useEffect(() => {
    if (focusTo === 'frame') frameHeading.current?.focus();
    if (focusTo === 'predict') firstChoice.current?.focus();
    if (focusTo) setFocusTo(null);
  }, [focusTo, at, predicting]);

  useEffect(() => {
    if (last && doneAck && !api.acked(doneAck)) api.setAck(doneAck, true);
  }, [last, doneAck, api]);

  const forward = () => {
    if (last) return;
    if (next.question && next.options?.length && !picks[next.id]) {
      setChoice('');
      setPredicting(true);
      setFocusTo('predict');
      return;
    }
    setPredicting(false);
    setAt(at + 1);
    if (at + 1 === frames.length - 1) setFocusTo('frame'); // "next" is about to disable itself
  };
  const back = () => {
    if (predicting) {
      setPredicting(false);
      setFocusTo('frame');
      return;
    }
    if (at > 0) {
      setAt(at - 1);
      if (at - 1 === 0) setFocusTo('frame'); // "back" is about to disable itself
    }
  };
  const reveal = () => {
    if (!choice || !next) return;
    setPicks({ ...picks, [next.id]: choice });
    setPredicting(false);
    setAt(at + 1);
    setFocusTo('frame'); // the reveal button unmounts
  };
  const onKey = (e: React.KeyboardEvent<HTMLElement>) => {
    if ((e.target as HTMLElement).closest('input, textarea, select, summary')) return;
    const rtl = getComputedStyle(e.currentTarget).direction === 'rtl';
    const fwd = rtl ? 'ArrowLeft' : 'ArrowRight';
    const bwd = rtl ? 'ArrowRight' : 'ArrowLeft';
    if (e.key === fwd) {
      e.preventDefault();
      forward();
    } else if (e.key === bwd) {
      e.preventDefault();
      back();
    }
  };
  const picked = frame.options?.find((o) => o.id === picks[frame.id]);

  return (
    <section aria-labelledby={`${id}-t`} className={BOX} data-testid="agent-turn-stepper" onKeyDown={onKey}>
      <h4 id={`${id}-t`} className="font-hebrew text-[17px]">
        {block.caption ? <InlineText text={block.caption} /> : 'תור של סוכן קוד'}
      </h4>
      <span className="pill pill-warn justify-self-start" data-testid="turn-illustration-label">
        המחשה של הדפוס, לא הקלטה של Antigravity
      </span>
      <p className="text-[13px] text-ink-2">
        עוברים בכפתורים «הבא» ו«הקודם», או בחיצים. לפני כל צעד חדש בוחרים ניחוש – בלי ציון, ושום דבר לא נשמר.
      </p>
      <p id={`${id}-live`} aria-live="polite" className="text-[14px] font-semibold" data-testid="turn-live">
        {predicting && next ? (
          <>
            לפני צעד <Ltr>{at + 2}</Ltr>: מה לדעתכם יקרה?
          </>
        ) : (
          <>
            צעד <Ltr>{at + 1}</Ltr> מתוך <Ltr>{frames.length}</Ltr>: <InlineText text={frame.title} />
          </>
        )}
      </p>

      {predicting && next ? (
        <fieldset className="grid grid-cols-1 gap-2 rounded-md bg-paper-2 p-3" data-testid="turn-predict">
          <legend className="mb-1 text-[15px] font-semibold">
            <InlineText text={next.question ?? ''} />
          </legend>
          {next.options?.map((o, i) => (
            <label key={o.id} className="flex min-h-[44px] items-center gap-2 rounded-md px-2 text-[15px]">
              <input
                ref={i === 0 ? firstChoice : undefined}
                type="radio"
                name={`${id}-predict-${next.id}`}
                value={o.id}
                checked={choice === o.id}
                onChange={() => setChoice(o.id)}
                className={FOCUS}
              />
              <InlineText text={o.text} />
            </label>
          ))}
          <button
            type="button"
            onClick={reveal}
            disabled={!choice}
            className={`min-h-[44px] justify-self-start rounded-md bg-forest px-4 font-semibold text-paper disabled:opacity-50 ${FOCUS}`}
          >
            גלו מה קורה
          </button>
        </fieldset>
      ) : (
        <article className="grid grid-cols-1 gap-2 rounded-md bg-paper-2 p-3" data-testid="turn-frame" data-frame={frame.id}>
          <h5 ref={frameHeading} tabIndex={-1} className={`text-[15px] font-semibold ${FOCUS}`} data-testid="turn-frame-title">
            <InlineText text={frame.title} />
          </h5>
          {frame.reveal && picked ? (
            <div className="rounded-md border border-info-soft bg-card p-2 text-[14px]" data-testid="turn-reveal">
              <p>
                <b>ניחשתם:</b> <InlineText text={picked.text} />
              </p>
              <p>
                <b>מה קורה בפועל:</b> <InlineText text={frame.reveal} />
              </p>
            </div>
          ) : null}
          <details className="text-[14px]">
            <summary className="min-h-[44px] cursor-pointer py-2 font-semibold">
              מה בהקשר (<Ltr>{frame.context.length}</Ltr>)
            </summary>
            <ul className="list-disc ps-5">
              {frame.context.map((c, i) => (
                <li key={i}>
                  <InlineText text={c} />
                </li>
              ))}
            </ul>
          </details>
          <p className="text-[14px]">
            <span className={`pill me-2 ${frame.model_output_kind === 'tool_request' ? 'pill-warn' : 'pill-ok'}`}>
              {frame.model_output_kind === 'tool_request' ? 'פלט המודל: בקשת כלי' : 'פלט המודל: טקסט אליכם'}
            </span>
            <InlineText text={frame.model_output} />
          </p>
          <p className="text-[14px]">
            <b>מה ה-harness עושה:</b> <InlineText text={frame.harness} />
          </p>
          <p className="text-[14px]">
            <b>תוצאת הכלי:</b> {frame.tool_result ? <InlineText text={frame.tool_result} /> : 'אין – התור נגמר.'}
          </p>
        </article>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={back}
          disabled={at === 0 && !predicting}
          className={`min-h-[44px] rounded-md border border-forest px-4 font-semibold text-forest disabled:opacity-50 ${FOCUS}`}
        >
          → הקודם
        </button>
        <button
          type="button"
          onClick={forward}
          disabled={last || predicting}
          className={`min-h-[44px] rounded-md border border-forest px-4 font-semibold text-forest disabled:opacity-50 ${FOCUS}`}
        >
          הבא ←
        </button>
        {last ? (
          <span className="text-[14px] text-ink-2" data-testid="turn-done">
            ✓ התור נגמר: המודל ענה בטקסט.
          </span>
        ) : null}
      </div>
      {doneAck ? (
        <p aria-live="polite" className="text-[14px]" data-testid="turn-walked">
          {done ? (
            <span className="text-ok">✓ עברתם על כל ההמחשה – זה נרשם בשלב.</span>
          ) : (
            <span className="text-ink-2">הסימון «עברתי על ההמחשה» נרשם לבד, כשמגיעים לצעד האחרון.</span>
          )}
        </p>
      ) : null}
    </section>
  );
}
