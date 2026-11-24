import { readFile } from "node:fs/promises"
import { request } from "node:http"
import { homedir } from "node:os"
import { join } from "node:path"
import type { View } from "./state.ts"
import type { Preview } from "./requests.ts"

export function discoveryPath(): string {
  const root = process.platform === "win32"
    ? process.env.LOCALAPPDATA ?? join(homedir(), "AppData", "Local")
    : process.env.XDG_CACHE_HOME ?? join(homedir(), ".cache")
  return join(root, "openbuddy", "bridge.json")
}

export async function publish(source: string, sequence: number, view: View, signal: AbortSignal,
                              choice?: Preview) {
  await bridgeRequest("POST", "/state", { v: 1, source, sequence, ...view,
    label: view.label.slice(0, 24), ...(choice ? { choice } : {}) }, signal)
}

export async function nextChoice(source: string, signal: AbortSignal): Promise<{
  touch: boolean; choice?: { kind: "form" | "permission"; id: string; index: number }
  navigate?: { kind: "form" | "permission"; id: string; step: number }
}> {
  const result = await bridgeRequest("GET", `/choice?source=${encodeURIComponent(source)}`, undefined, signal)
  return { touch: result.touch === true, choice: result.choice ?? undefined, navigate: result.navigate ?? undefined }
}

async function bridgeRequest(method: "GET" | "POST", path: string, input: unknown,
                             signal: AbortSignal): Promise<any> {
  const text = await readFile(discoveryPath(), "utf8")
  if (text.length > 1024) throw new Error("Invalid bridge discovery")
  const target = JSON.parse(text)
  if (target.product !== "openbuddy" || target.v !== 1 || !Number.isInteger(target.port)
      || target.port < 1024 || target.port > 65535 || !/^[a-f0-9]{64}$/.test(target.token)) {
    throw new Error("Invalid bridge discovery")
  }
  const body = input === undefined ? undefined : JSON.stringify(input)
  // Native loopback HTTP avoids environment-proxy handling by fetch implementations.
  return await new Promise<any>((resolve, reject) => {
    const outgoing = request({
      hostname: "127.0.0.1", port: target.port, path, method, agent: false,
      headers: { "Authorization": `Bearer ${target.token}`, ...(body === undefined ? {} : {
        "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) }) },
      signal: AbortSignal.any([signal, AbortSignal.timeout(1500)]),
    }, response => {
      let text = ""
      response.on("error", reject)
      response.on("end", () => {
        if (response.statusCode === 200) {
          try { resolve(JSON.parse(text)) } catch (error) { reject(error) }
        } else reject(new Error("Bridge rejected request"))
      })
      response.on("data", chunk => { text += chunk; if (text.length > 4096) response.destroy() })
    })
    outgoing.on("error", reject)
    outgoing.end(body)
  })
}
