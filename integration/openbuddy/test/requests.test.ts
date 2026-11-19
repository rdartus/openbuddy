import { test } from "node:test"
import assert from "node:assert/strict"
import { formRequest, permissionRequest, preview, submitChoice } from "../src/requests.ts"
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
  })
})

test("free-form, ambiguous and multi-field forms remain on OpenCode", () => {
  assert.equal(formRequest({ ...form, fields: [form.fields[0], form.fields[0]] }), undefined)
  assert.equal(formRequest({ ...form, fields: [{ key: "name", type: "string" }] }), undefined)
  assert.equal(formRequest({ ...form, fields: [{ ...form.fields[0], custom: true }] }), undefined)
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
  const item = formRequest(form)!
  const writes: unknown[] = []
  const client = { session: { form: {
    get: async () => ({ ...form, state: { status: "pending" } }),
    reply: async (input: unknown) => { writes.push(input) },
  } } } as unknown as ReturnType<typeof OpenCode.make>
  assert.equal(await submitChoice(item, 1, client, new AbortController().signal), true)
  assert.deepEqual(writes, [{ sessionID: "ses_1", formID: "frm_1", answer: { language: "rust" } }])
})
