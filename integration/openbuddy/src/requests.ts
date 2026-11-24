import type { View } from "./state.ts"
import type { OpenCode } from "@opencode/client"

export type ChoiceRequest = {
  kind: "form" | "permission"
  id: string
  sessionID: string
  title: string
  options: string[]
  values: string[]
  field?: string
  answerType?: "string" | "multiselect"
}
export type Preview = Pick<ChoiceRequest, "kind" | "id" | "title" | "options"> & { position: number; total: number }

// Form labels may lose unsupported glyphs, but never silently truncate a permission.
function display(text: unknown, limit: number): { value: string; stripped: boolean } | undefined {
  if (typeof text !== "string") return undefined
  const normalized = text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
    .replace(/[\u2018\u2019]/g, "'")
    .replace(/(\d)\u00b0/g, "$1 deg")
  if (/[\x00-\x1f\x7f]/.test(normalized)) return // Never merge lines or control characters.
  const ascii = normalized.replace(/[^\x20-\x7e]/g, "").trim()
  return ascii && ascii.length <= limit ? { value: ascii, stripped: ascii !== normalized.trim() } : undefined
}

export function formRequest(form: any): ChoiceRequest | undefined {
  if (!form || !/^[\w-]{1,48}$/.test(form.id) || typeof form.sessionID !== "string"
      || !Array.isArray(form.fields) || form.fields.length !== 1) return
  const field = form.fields[0]
  if ((field.type !== "string" && !(field.type === "multiselect" && field.maxItems === 1
      && (field.minItems === undefined || field.minItems <= 1)))
      || typeof field.key !== "string" || !field.key || field.hidden
      || field.when?.length
      || !Array.isArray(field.options) || field.options.length < 2 || field.options.length > 8) return
  const title = display([form.title, field.title, field.description,
    field.custom === true ? "Other answers: use OpenCode" : undefined].filter(Boolean).join(" - "), 600)
  const options: Array<ReturnType<typeof display>> = field.options.map((option: any) => display(
    [option.label, option.description].filter(Boolean).join(" - "), 120))
  if (!title || options.some(option => !option)
      || new Set(options.map(option => option?.value)).size !== options.length
      || field.options.some((option: any) => typeof option.value !== "string")
      || new Set(field.options.map((option: any) => option.value)).size !== field.options.length) return
  const visibleTitle = (title.stripped || options.some(option => option?.stripped)
    ? "TEXT FILTERED - " : "") + title.value
  if (visibleTitle.length > 600) return
  return { kind: "form", id: form.id, sessionID: form.sessionID, title: visibleTitle,
    options: options.map(option => option!.value), values: field.options.map((option: any) => option.value),
    field: field.key, answerType: field.type }
}

export function permissionRequest(request: any): ChoiceRequest | undefined {
  if (!request || !/^[\w-]{1,48}$/.test(request.id) || typeof request.sessionID !== "string"
      || typeof request.action !== "string" || !Array.isArray(request.resources)
      || !Array.isArray(request.save) || request.save.length === 0
      || request.resources.some((item: unknown) => typeof item !== "string")
      || request.save.some((item: unknown) => typeof item !== "string")) return
  // Unlike a form label, a permission's path and persistent save scope are verbatim.
  const raw = [request.action, ...request.resources, request.message,
    `ALWAYS: ${request.save.join(", ")}`].filter(Boolean).join(" - ")
  const title = /^[\x20-\x7e]+$/.test(raw) && raw.length <= 600 ? raw : undefined
  if (!title) return
  return { kind: "permission", id: request.id, sessionID: request.sessionID,
    title, options: ["REFUSE", "AUTORISER UNE FOIS", "TOUJOURS AUTORISER"],
    values: ["reject", "once", "always"] }
}

export function preview(view: View, requests: Map<string, ChoiceRequest>, selected?: string): Preview | undefined {
  const kind = view.state === "permission" ? "permission" : view.state === "question" ? "form" : undefined
  const items = [...requests.values()].filter(item => item.kind === kind)
  if (items.length > 100) return // The device cannot show a truthful bounded request count.
  const position = Math.max(0, items.findIndex(item => `${item.kind}:${item.id}` === selected))
  const request = items[position]
  return request && { kind: request.kind, id: request.id, title: request.title,
    options: request.options, position: position + 1, total: items.length }
}

export function navigate(view: View, requests: Map<string, ChoiceRequest>, id: string, step: number): string | undefined {
  const current = preview(view, requests, id)
  if (!current || current.id !== id.split(":").slice(1).join(":") || current.total < 2 || ![-1, 1].includes(step)) return
  const items = [...requests.values()].filter(item => item.kind === current.kind)
  const item = items[(current.position - 1 + step + items.length) % items.length]
  return `${item.kind}:${item.id}`
}

export async function submitChoice(item: ChoiceRequest, index: number,
                                   client: ReturnType<typeof OpenCode.make>, signal: AbortSignal): Promise<boolean> {
  if (!Number.isInteger(index) || index < 0 || index >= item.values.length) return false
  const request = { signal }
  if (item.kind === "form") {
    const current = await client.session.form.get({ sessionID: item.sessionID, formID: item.id }, request)
    if (current.state.status !== "pending" || JSON.stringify(formRequest(current)) !== JSON.stringify(item)) {
      return false
    }
    await client.session.form.reply({ sessionID: item.sessionID, formID: item.id,
      answer: { [item.field!]: item.answerType === "multiselect" ? [item.values[index]] : item.values[index] } }, request)
  } else {
    const current = await client.permission.get({ sessionID: item.sessionID, requestID: item.id }, request)
    if (JSON.stringify(permissionRequest(current)) !== JSON.stringify(item)) return false
    await client.permission.reply({ sessionID: item.sessionID, requestID: item.id,
      decision: item.values[index] as "once" | "always" | "reject" }, request)
  }
  return true
}
