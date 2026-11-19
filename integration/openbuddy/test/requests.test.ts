import { test } from "node:test"
import assert from "node:assert/strict"
import { formRequest, permissionRequest, preview, navigate, submitChoice } from "../src/requests.ts"
import type { OpenCode } from "@opencode/client"

const form = { id: "frm_1", sessionID: "ses_1", title: "Which language?", fields: [
  { key: "language", type: "string", options: [
    { value: "python", label: "Python" }, { value: "rust", label: "Rust", description: "fast" },
  ] },
] }

test("one string option field keeps the exact answer values on the service", () => {
  const item = formRequest(form)
  assert.deepEqual(item?.options, ["Python", "Rust - fast"])
  assert.deepEqual(item?.values, ["python", "rust"])
  const view = { state: "question", label: "Question", pending_forms: 1,
    pending_permissions: 0, active_sessions: 1 } as const
  assert.deepEqual(preview(view, new Map([["form:frm_1", item!]])), {
    kind: "form", id: "frm_1", title: "Which language?", options: ["Python", "Rust - fast"],
    position: 1, total: 1,
  })
})

test("navigation cycles only through representable requests of the current priority", () => {
  const view = { state: "permission", label: "Permission", pending_forms: 1,
    pending_permissions: 2, active_sessions: 1 } as const
  const first = permissionRequest({ id: "p1", sessionID: "s1", action: "read", resources: ["a.py"], save: ["*.py"] })!
  const second = permissionRequest({ id: "p2", sessionID: "s2", action: "read", resources: ["b.py"], save: ["*.py"] })!
  const items = new Map([["permission:p1", first], ["form:frm_1", formRequest(form)!], ["permission:p2", second]])
  assert.equal(preview(view, items)?.total, 2)
  assert.equal(navigate(view, items, "permission:p1", 1), "permission:p2")
  assert.equal(preview(view, items, "permission:p2")?.position, 2)
  assert.equal(navigate(view, items, "permission:p1", -1), "permission:p2")
  assert.equal(navigate(view, items, "permission:p1", 0), undefined)
  assert.equal(navigate(view, items, "permission:wrong", 1), undefined)
  const many = new Map(Array.from({ length: 101 }, (_, index) => {
    const item = { ...first, id: `p${index}` }
    return [`permission:${item.id}`, item] as const
  }))
  assert.equal(preview(view, many), undefined)
})

test("free-form, ambiguous and multi-field forms remain on OpenCode", () => {
  assert.equal(formRequest({ ...form, fields: [form.fields[0], form.fields[0]] }), undefined)
  assert.equal(formRequest({ ...form, fields: [{ key: "name", type: "string" }] }), undefined)
  const custom = formRequest({ ...form, fields: [{ ...form.fields[0], custom: true }] })
  assert.deepEqual(custom?.values, ["python", "rust"])
  assert.match(custom!.title, /Other answers: use OpenCode$/)
  const punctuation = formRequest({ ...form, fields: [{ ...form.fields[0], options: [
    { value: "python", label: "C’est prêt" }, { value: "rust", label: "D’accord" },
  ] }] })
  assert.deepEqual(punctuation?.options, ["C'est pret", "D'accord"])
  assert.deepEqual(punctuation?.values, ["python", "rust"])
  const angles = formRequest({ ...form, title: "Tourner de 180\u00b0", fields: [{ ...form.fields[0], options: [
    { value: "left", label: "90\u00b0 a gauche" }, { value: "right", label: "90\u00b0 a droite" },
  ] }] })
  assert.equal(angles?.title, "Tourner de 180 deg")
  assert.deepEqual(angles?.options, ["90 deg a gauche", "90 deg a droite"])
  assert.deepEqual(angles?.values, ["left", "right"])
  assert.equal(formRequest({ ...form, title: "Numero n\u00b0" })?.title,
    "TEXT FILTERED - Numero n")
  const filtered = formRequest({ ...form, fields: [{ ...form.fields[0], options: [
    { value: "python", label: "Python \u{1f512}" }, { value: "rust", label: "Rust" },
  ] }] })
  assert.equal(filtered?.title, "TEXT FILTERED - Which language?")
  assert.deepEqual(filtered?.options, ["Python", "Rust"])
  assert.deepEqual(filtered?.values, ["python", "rust"])
  assert.equal(formRequest({ ...form, title: "\u{1f512}" }), undefined)
  assert.equal(formRequest({ ...form, fields: [{ ...form.fields[0], options: [
    { value: "python", label: "\u{1f512}" }, { value: "rust", label: "Rust" },
  ] }] }), undefined)
  assert.equal(formRequest({ ...form, fields: [{ ...form.fields[0], options: [
    { value: "one", label: "Yes \u{1f512}" }, { value: "two", label: "Yes \u{1f511}" },
  ] }] }), undefined)
  assert.equal(formRequest({ ...form, title: "Choose\nnow" }), undefined)
  assert.equal(formRequest({ ...form, title: "x".repeat(590) + " \u{1f512}" }), undefined)
  assert.equal(formRequest({ ...form, fields: [{ ...form.fields[0], options: [
    { value: "one", label: "same" }, { value: "two", label: "same" },
  ] }] }), undefined)
})

test("multiselect with exactly one choice replies as a one-item array", async () => {
  const single = { ...form, fields: [{ ...form.fields[0], type: "multiselect", minItems: 1, maxItems: 1 }] }
  const item = formRequest(single)!
  assert.equal(item.answerType, "multiselect")
  const writes: unknown[] = []
  const client = { session: { form: {
    get: async () => ({ ...single, state: { status: "pending" } }),
    reply: async (input: unknown) => { writes.push(input) },
  } } } as unknown as ReturnType<typeof OpenCode.make>
  assert.equal(await submitChoice(item, 0, client, new AbortController().signal), true)
  assert.deepEqual(writes, [{ sessionID: "ses_1", formID: "frm_1", answer: { language: ["python"] } }])
  assert.equal(formRequest({ ...single, fields: [{ ...single.fields[0], maxItems: 2 }] }), undefined)
})

test("permission exposes denial, once and always only with the full saved scope", () => {
  const request = { id: "per_1", sessionID: "ses_1", action: "read", resources: ["a.py"],
    save: ["*.py"], message: "Check file" }
  const item = permissionRequest(request)
  assert.deepEqual(item?.values, ["reject", "once", "always"])
  assert.deepEqual(item?.options, ["REFUSE", "AUTORISER UNE FOIS", "TOUJOURS AUTORISER"])
  assert.match(item!.title, /ALWAYS: \*\.py/)
  assert.equal(permissionRequest({ ...request, save: undefined }), undefined)
  assert.equal(permissionRequest({ ...request, save: [] }), undefined)
  assert.equal(permissionRequest({ ...request, resources: ["x".repeat(620)] }), undefined)
  assert.equal(permissionRequest({ ...request, resources: ["untrusted\npath"] }), undefined)
  assert.equal(permissionRequest({ ...request, resources: ["180\u00b0"] }), undefined)
})

test("permission reply uses the exact session and pending ID; stale scope is refused", async () => {
  const original = { id: "per_1", sessionID: "ses_1", action: "write", resources: ["file.py"],
    save: ["*.py"], message: "Edit file" }
  const item = permissionRequest(original)!
  const writes: unknown[] = []
  let live = original
  const client = { permission: {
    get: async () => live,
    reply: async (input: unknown) => { writes.push(input) },
  } } as unknown as ReturnType<typeof OpenCode.make>
  const signal = new AbortController().signal
  assert.equal(await submitChoice(item, 2, client, signal), true)
  assert.deepEqual(writes, [{ sessionID: "ses_1", requestID: "per_1", decision: "always" }])
  live = { ...original, resources: ["other.py"] }
  assert.equal(await submitChoice(item, 2, client, signal), false)
  assert.equal(await submitChoice(item, 10, client, signal), false)
  assert.equal(writes.length, 1)
})

test("form answer sends the unmodified option value, not its display label", async () => {
  const filtered = { ...form, fields: [{ ...form.fields[0], options: [
    { value: "python", label: "Python \u{1f512}" }, { value: "rust", label: "Rust" },
  ] }] }
  const item = formRequest(filtered)!
  const writes: unknown[] = []
  const client = { session: { form: {
    get: async () => ({ ...filtered, state: { status: "pending" } }),
    reply: async (input: unknown) => { writes.push(input) },
  } } } as unknown as ReturnType<typeof OpenCode.make>
  assert.equal(await submitChoice(item, 1, client, new AbortController().signal), true)
  assert.deepEqual(writes, [{ sessionID: "ses_1", formID: "frm_1", answer: { language: "rust" } }])
})
