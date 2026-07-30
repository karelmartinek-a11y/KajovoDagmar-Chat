class KajoRecorderProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.targetRate = 24000;
    this.frameSamples = 480;
    this.buffer = [];
    this.sourcePosition = 0;
    this.lastSample = 0;
  }

  process(inputs) {
    const channel = inputs[0]?.[0];
    if (!channel || channel.length === 0) return true;
    const ratio = sampleRate / this.targetRate;
    let position = this.sourcePosition;
    while (position < channel.length) {
      const leftIndex = Math.floor(position);
      const rightIndex = Math.min(leftIndex + 1, channel.length - 1);
      const fraction = position - leftIndex;
      const left = leftIndex >= 0 ? channel[leftIndex] : this.lastSample;
      const right = channel[rightIndex];
      const sample = left + (right - left) * fraction;
      this.buffer.push(Math.max(-1, Math.min(1, sample)));
      position += ratio;
      if (this.buffer.length >= this.frameSamples) {
        const pcm = new Int16Array(this.frameSamples);
        for (let index = 0; index < this.frameSamples; index += 1) {
          const value = this.buffer[index];
          pcm[index] = value < 0 ? value * 0x8000 : value * 0x7fff;
        }
        this.buffer.splice(0, this.frameSamples);
        this.port.postMessage(pcm.buffer, [pcm.buffer]);
      }
    }
    this.sourcePosition = position - channel.length;
    this.lastSample = channel[channel.length - 1];
    return true;
  }
}

registerProcessor('kajovodagmar-recorder', KajoRecorderProcessor);
