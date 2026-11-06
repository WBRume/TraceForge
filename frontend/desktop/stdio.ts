const guarded = new WeakSet<NodeJS.WritableStream>()

// A desktop app can outlive the terminal that launched it. Node also forwards
// worker diagnostics to these streams, including after that terminal closes.
export function guardClosedOutputPipes() {
  for (const stream of [process.stdout, process.stderr]) {
    if (guarded.has(stream)) continue
    guarded.add(stream)
    stream.on('error', (error: NodeJS.ErrnoException) => {
      if (error.code !== 'EPIPE') throw error
    })
  }
}
