export const parseSseJsonData = (rawData: string, parseErrorMessage = '流式响应解析失败'): Record<string, unknown> => {
  try {
    const parsed = JSON.parse(rawData)
    if (!parsed || typeof parsed !== 'object') return {}
    return parsed as Record<string, unknown>
  } catch (error) {
    throw new Error(error instanceof Error ? error.message : parseErrorMessage)
  }
}

export type ParsedSseFrame = {
  eventName?: string
  data: Record<string, unknown>
}

export const parseSseFrameFields = (frame: string, options: { parseErrorMessage?: string } = {}): ParsedSseFrame | null => {
  const trimmed = frame.trim()
  if (!trimmed) return null

  let eventName: string | undefined
  const dataLines: string[] = []

  trimmed.split(/\r?\n/).forEach((line) => {
    if (!line || line.startsWith(':')) return
    const separatorIndex = line.indexOf(':')
    const fieldName = separatorIndex >= 0 ? line.slice(0, separatorIndex) : line
    const rawValue = separatorIndex >= 0 ? line.slice(separatorIndex + 1) : ''
    const value = rawValue.startsWith(' ') ? rawValue.slice(1) : rawValue

    if (fieldName === 'event') {
      eventName = value
      return
    }
    if (fieldName === 'data') {
      dataLines.push(value)
    }
  })

  const rawData = dataLines.join('\n')
  const data = rawData ? parseSseJsonData(rawData, options.parseErrorMessage) : {}
  return { eventName, data }
}

export async function* readSseStream<T>(
  response: Response,
  mapFrame: (frame: ParsedSseFrame) => T | null,
  options: { parseErrorMessage?: string } = {},
): AsyncGenerator<T> {
  const reader = response.body?.getReader()
  if (!reader) throw new Error('当前浏览器不支持流式回复')

  const decoder = new TextDecoder()
  let buffer = ''

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ''

      for (const frameText of frames) {
        const frame = parseSseFrameFields(frameText, options)
        if (!frame) continue
        const event = mapFrame(frame)
        if (event) yield event
      }
    }

    buffer += decoder.decode()
    const lastFrame = parseSseFrameFields(buffer, options)
    if (lastFrame) {
      const event = mapFrame(lastFrame)
      if (event) yield event
    }
  } finally {
    reader.releaseLock()
  }
}
