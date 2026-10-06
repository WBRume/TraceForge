const { speechBuildOptions, validateSpeechAssets } = require('./speech/build-options.cjs')
const speech = speechBuildOptions()
// Target-specific validation also runs for cross-platform electron-builder invocations.
module.exports = {
  ...require('../package.json').build,
  beforePack: context => validateSpeechAssets(speech, context.electronPlatformName, require('builder-util').Arch[context.arch]),
  extraResources: speech.bundled ? [{ from: speech.assetsDirectory, to: 'offline-speech', filter: ['**/*'] }] : [],
  mac: {
    ...require('../package.json').build.mac,
    ...(speech.mode !== 'off' ? { extendInfo: { NSMicrophoneUsageDescription: 'TraceForge uses the microphone to transcribe your voice into a message draft.' } } : {}),
  },
}
