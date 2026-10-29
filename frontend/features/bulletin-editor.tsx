"use client";
/** Editing a weekly bulletin draft on the website, and translating it. Each save is a new
 * draft version; its Word document and maps are made again from it. */
import { useId, useState } from "react";
import { Languages, Plus, Save, Trash2 } from "lucide-react";
import { Button, Card, ErrorState, Notice } from "@/components/ui";
import { useActor } from "@/lib/actor";
import { useLanguage } from "@/lib/language";
import { mutate } from "@/services/api";
import type { Bulletin, BulletinSection } from "@/types/workflows";

const EDITABLE = ["headline", "decision_support", "rainfall", "focus"];

/** Paragraphs as the editor shows them: separated by an empty line. */
const join = (paragraphs: string[]) => paragraphs.join("\n\n");
const split = (text: string) =>
  text
    .split(/\n\s*\n/)
    .map((p) => p.replace(/\s+/g, " ").trim())
    .filter(Boolean);

export const TRANSLATIONS: Record<string, string> = {
  sw: "Kiswahili",
  am: "Amharic",
  so: "Somali",
  ar: "Arabic",
  fr: "French",
  ti: "Tigrinya",
  om: "Afaan Oromo",
  rw: "Kinyarwanda",
  rn: "Kirundi",
  lg: "Luganda",
};

type Note = { title: string; text: string; original?: string };

export function DraftEditor({
  draft,
  onSaved,
  onCancel,
}: {
  draft: Bulletin;
  onSaved: (draft: Bulletin) => void;
  onCancel: () => void;
}) {
  const [actor] = useActor();
  const uid = useId();
  const sections = draft.facts.sections;
  const fixed = sections.filter((s) => EDITABLE.includes(s.key));
  const [texts, setTexts] = useState<Record<string, string>>(() =>
    Object.fromEntries(fixed.map((s) => [s.key, join(s.text)])),
  );
  const [why, setWhy] = useState(
    sections.find((s) => s.key === "focus")?.why ?? "",
  );
  const [notes, setNotes] = useState<Note[]>(() =>
    sections
      .filter((s) => s.note)
      .map((s) => ({ title: s.title, text: join(s.text), original: s.title })),
  );
  const [summary, setSummary] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = async () => {
    const changes = fixed
      .filter(
        (s) =>
          join(s.text) !== texts[s.key] ||
          (s.key === "focus" && (s.why ?? "") !== why),
      )
      .map((s: BulletinSection) => ({
        section: s.key,
        paragraphs: split(texts[s.key]),
        ...(s.key === "focus" && why.trim() ? { why: why.trim() } : {}),
      }));
    const kept = new Set(notes.map((n) => n.original).filter(Boolean));
    const remove_notes = sections
      .filter((s) => s.note && !kept.has(s.title))
      .map((s) => s.title);
    const add_notes = notes
      .filter((n) => n.title.trim() && split(n.text).length)
      .filter((n) => {
        const before = sections.find((s) => s.note && s.title === n.original);
        return (
          !before || before.title !== n.title || join(before.text) !== n.text
        );
      })
      .map((n) => ({ title: n.title.trim(), paragraphs: split(n.text) }));
    // A renamed section replaces the one it was.
    for (const n of notes)
      if (n.original && n.original !== n.title.trim())
        remove_notes.push(n.original);
    if (!changes.length && !add_notes.length && !remove_notes.length) {
      setError("Nothing has changed yet.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      onSaved(
        await mutate<Bulletin>(`/bulletins/${draft.id}/edit`, {
          changes,
          add_notes,
          remove_notes,
          summary: summary || "Edited on the website",
          actor: actor || null,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      eyebrow="Edit the draft"
      title={draft.title}
      subtitle="Change the wording, add or remove your own sections, then save. The edited bulletin is a new version; its Word document and web page are made again from it. The country table and the forecast note come from the forecast and are not edited here."
    >
      <div className="draft-editor">
        {fixed.map((section) => (
          <div key={section.key} className="field">
            <label htmlFor={`${uid}-${section.key}`}>{section.title}</label>
            <textarea
              id={`${uid}-${section.key}`}
              aria-describedby={`${uid}-${section.key}-hint`}
              rows={Math.min(
                14,
                Math.max(
                  3,
                  // About 100 characters a line, and the empty line between paragraphs.
                  section.text.reduce(
                    (n, p) => n + Math.ceil(p.length / 100) + 1,
                    0,
                  ),
                ),
              )}
              value={texts[section.key]}
              onChange={(e) =>
                setTexts((old) => ({ ...old, [section.key]: e.target.value }))
              }
            />
            <span id={`${uid}-${section.key}-hint`} className="hint">
              Separate paragraphs with an empty line.
            </span>
            {section.key === "focus" && (
              <>
                <label htmlFor={`${uid}-why`} className="hint">
                  Why this country is the focus
                </label>
                <textarea
                  id={`${uid}-why`}
                  rows={2}
                  value={why}
                  onChange={(e) => setWhy(e.target.value)}
                />
              </>
            )}
          </div>
        ))}
        {notes.map((note, index) => (
          <div key={index} className="draft-note">
            <label className="field">
              Section title
              <input
                value={note.title}
                maxLength={80}
                onChange={(e) =>
                  setNotes((old) =>
                    old.map((n, i) =>
                      i === index ? { ...n, title: e.target.value } : n,
                    ),
                  )
                }
              />
            </label>
            <label className="field">
              Text
              <textarea
                rows={4}
                value={note.text}
                onChange={(e) =>
                  setNotes((old) =>
                    old.map((n, i) =>
                      i === index ? { ...n, text: e.target.value } : n,
                    ),
                  )
                }
              />
            </label>
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setNotes((old) => old.filter((_, i) => i !== index))
              }
            >
              <Trash2 size={15} /> Remove this section
            </Button>
          </div>
        ))}
        <div>
          <Button
            variant="outline"
            size="sm"
            disabled={notes.length >= 6}
            onClick={() => setNotes((old) => [...old, { title: "", text: "" }])}
          >
            <Plus size={15} /> Add a section (an advisory, impacts, guidance)
          </Button>
        </div>
        <label className="field">
          What you changed (for the review record)
          <input
            value={summary}
            maxLength={300}
            placeholder="e.g. Clearer headline; added advice for farmers"
            onChange={(e) => setSummary(e.target.value)}
          />
        </label>
        {error && <ErrorState message={error} />}
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <Button onClick={save} disabled={saving}>
            <Save size={16} /> {saving ? "Saving…" : "Save as a new version"}
          </Button>
          <Button variant="outline" onClick={onCancel} disabled={saving}>
            Cancel
          </Button>
        </div>
      </div>
    </Card>
  );
}

export function TranslateDraft({
  draft,
  onDone,
}: {
  draft: Bulletin;
  onDone: (draft: Bulletin) => void;
}) {
  const [actor] = useActor();
  // The site's language (the Copilot's too): choosing one here changes it there.
  const [shared, setLanguage] = useLanguage();
  const language = shared in TRANSLATIONS ? shared : "sw";
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <div className="draft-translate">
      <label className="field">
        Language
        <select value={language} onChange={(e) => setLanguage(e.target.value)}>
          {Object.entries(TRANSLATIONS).map(([code, name]) => (
            <option key={code} value={code}>
              {name}
            </option>
          ))}
        </select>
      </label>
      <Button
        variant="outline"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError(null);
          try {
            onDone(
              await mutate<Bulletin>(`/bulletins/${draft.id}/translate`, {
                language,
                actor: actor || null,
              }),
            );
          } catch (e) {
            setError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <Languages size={16} />{" "}
        {busy ? "Translating… about a minute" : "Translate this draft"}
      </Button>
      {error && <ErrorState message={error} />}
      <Notice>
        The AI service translates the wording; every figure must come back
        unchanged or nothing is saved. A speaker of the language checks the new
        version before a reviewer approves it.
      </Notice>
    </div>
  );
}
