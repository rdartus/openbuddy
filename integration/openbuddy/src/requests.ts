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
export type Preview = Pick<ChoiceRequest, "kind" | "id" | "title" | "options">

// The firmware's built-in font is ASCII only. Never silently truncate a choice
// or a permission: approving an incomplete description is unsafe.
function display(text: unknown, limit: number): string | undefined {
  if (typeof text !== "string") return undefined
  const ascii = text.normalize("NFKD").replace(/[\u0300-\u036f]/g, "")
  return ascii.length <= limit && /^[\x20-\x7e]*$/.test(ascii) ? ascii : undefined
}

export function formRequest(form: any): ChoiceRequest | undefined {
  if (!form || !/^[\w-]{1,48}$/.test(form.id) || typeof form.sessionID !== "string"
      || !Array.isArray(form.fields) || form.fields.length !== 1) return
  const field = form.fields[0]
  if ((field.type !== "string" && !(field.type === "multiselect" && field.maxItems === 1
      && (field.minItems === undefined || field.minItems <= 1)))
      || typeof field.key !== "string" || !field.key || field.hidden
      || field.when?.length || field.custom === true
      || !Array.isArray(field.options) || field.options.length < 2 || field.options.length > 8) return
  const title = display([form.title, field.title, field.description].filter(Boolean).join(" - "), 600)
  const options = field.options.map((option: any) => display(
    [option.label, option.description].filter(Boolean).join(" - "), 120))
  if (!title || options.some((option: string | undefined) => !option)
      || new Set(options).size !== options.length
      || field.options.some((option: any) => typeof option.value !== "string")
      || new Set(field.options.map((option: any) => option.value)).size !== field.options.length) return
  return { kind: "form", id: form.id, sessionID: form.sessionID, title,
    options: options as string[], values: field.options.map((option: any) => option.value),
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

export function preview(view: View, requests: Map<string, ChoiceRequest>): Preview | undefined {
  const kind = view.state === "permission" ? "permission" : view.state === "question" ? "form" : undefined
  const request = [...requests.values()].find(item => item.kind === kind)
  return request && { kind: request.kind, id: request.id, title: request.title, options: request.options }
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
