declare module '@adnsistemas/upng/cjs/UPNG.js' {
  const encoder: {
    encode(
      frames: ArrayBuffer[],
      width: number,
      height: number,
      paletteSize: number,
      delays: number[],
      options: { loop: number },
    ): ArrayBuffer
  }
  export default encoder
}
