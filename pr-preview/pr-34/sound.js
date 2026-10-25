// Marble sounds (Web Audio): a wooden "tock" when a marble lands after a
// fall, a rolling rumble while marbles roll, a clack for the seesaw and a
// chime at an exit. Each is synthesized unless sounds/sounds.json lists
// audio files for it (see that file). The audio context starts on the first
// user gesture (browsers block sound before one).
(function () {
  "use strict";

  const STORE = "marble-run-sound-v1";
  let ctx = null;
  let master = null;
  let rollGain = null;
  let rumble = null;          // the rolling loop's source node
  const samples = {};         // event -> [AudioBuffer], from sounds/sounds.json
  let samplesLoading = null;
  let enabled = true;
  try { enabled = localStorage.getItem(STORE) !== "off"; } catch (error) { /* private mode */ }

  function ensure() {
    if (!enabled) return null;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return null;
    if (!ctx) {
      ctx = new AudioCtx();
      master = ctx.createGain();
      master.gain.value = 0.7;
      master.connect(ctx.destination);
      rollGain = ctx.createGain();
      rollGain.gain.value = 0;
      rollGain.connect(master);
      startRumble();
      loadSamples();
    }
    if (ctx.state === "suspended") ctx.resume();
    return ctx;
  }

  function noiseBuffer(seconds) {
    const buffer = ctx.createBuffer(1, Math.floor(ctx.sampleRate * seconds), ctx.sampleRate);
    const data = buffer.getChannelData(0);
    for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
    return buffer;
  }

  async function loadSamples() {
    if (samplesLoading) return samplesLoading;
    samplesLoading = (async () => {
      let list = {};
      try {
        const response = await fetch("./sounds/sounds.json", { cache: "no-cache" });
        if (response.ok) list = await response.json();
      } catch (error) { return; }
      for (const [event, files] of Object.entries(list)) {
        if (event.startsWith("_")) continue;
        const names = Array.isArray(files) ? files : (files ? [files] : []);
        const buffers = [];
        for (const name of names) {
          try {
            const data = await (await fetch("./sounds/" + name)).arrayBuffer();
            buffers.push(await new Promise((ok, fail) => ctx.decodeAudioData(data, ok, fail)));
          } catch (error) {
            console.warn("sound file not loaded:", name, error);
          }
        }
        if (buffers.length) samples[event] = buffers;
      }
      if (samples.roll) startRumble();   // swap the synthesized loop for the file
    })();
    return samplesLoading;
  }

  function playSample(event, gain, rate = 1) {
    const list = samples[event];
    if (!list || !ensure()) return false;
    const source = ctx.createBufferSource();
    source.buffer = list[Math.floor(Math.random() * list.length)];
    source.playbackRate.value = rate;
    const g = ctx.createGain();
    g.gain.value = gain;
    source.connect(g).connect(master);
    source.start();
    return true;
  }

  // Continuous rolling sound; its gain follows the number of rolling marbles.
  function startRumble() {
    if (rumble) { try { rumble.stop(); } catch (error) { /* not started */ } }
    const source = ctx.createBufferSource();
    rumble = source;
    source.loop = true;
    if (samples.roll) {
      source.buffer = samples.roll[0];
      source.connect(rollGain);
      source.start();
      return;
    }
    source.buffer = noiseBuffer(2);
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = 900;
    band.Q.value = 0.8;
    const low = ctx.createBiquadFilter();
    low.type = "lowpass";
    low.frequency.value = 2200;
    source.connect(band).connect(low).connect(rollGain);
    source.start();
  }

  // Wooden knock: a short pitched body plus a click of noise.
  function knock(freq, strength, decay) {
    if (!ensure()) return;
    const t = ctx.currentTime;
    const osc = ctx.createOscillator();
    osc.type = "triangle";
    osc.frequency.setValueAtTime(freq * 1.4, t);
    osc.frequency.exponentialRampToValueAtTime(freq, t + 0.02);
    const body = ctx.createGain();
    body.gain.setValueAtTime(0.0001, t);
    body.gain.exponentialRampToValueAtTime(0.5 * strength, t + 0.004);
    body.gain.exponentialRampToValueAtTime(0.0001, t + decay);
    osc.connect(body).connect(master);
    osc.start(t);
    osc.stop(t + decay + 0.02);

    const click = ctx.createBufferSource();
    click.buffer = noiseBuffer(0.03);
    const hp = ctx.createBiquadFilter();
    hp.type = "highpass";
    hp.frequency.value = 2500;
    const clickGain = ctx.createGain();
    clickGain.gain.setValueAtTime(0.25 * strength, t);
    clickGain.gain.exponentialRampToValueAtTime(0.0001, t + 0.03);
    click.connect(hp).connect(clickGain).connect(master);
    click.start(t);
  }

  const api = {
    get enabled() { return enabled; },
    setEnabled(on) {
      enabled = Boolean(on);
      try { localStorage.setItem(STORE, enabled ? "on" : "off"); } catch (error) { /* ignore */ }
      if (!enabled && rollGain) rollGain.gain.setTargetAtTime(0, ctx.currentTime, 0.05);
      if (enabled) ensure();
    },
    unlock() { ensure(); },
    // Events that use sound files (after the first tap has loaded them).
    get fromFiles() { return Object.keys(samples); },
    // A marble lands after falling `dropCm`.
    land(dropCm) {
      const strength = Math.min(1, 0.35 + dropCm / 25);
      if (playSample("land", strength, 0.92 + Math.random() * 0.16)) return;
      knock(700 + Math.random() * 250, strength, 0.12);
    },
    seesaw() { if (!playSample("seesaw", 0.9)) knock(260, 0.9, 0.22); },
    exit() {
      if (playSample("exit", 0.6) || !ensure()) return;
      const t = ctx.currentTime;
      [1318.5, 1760].forEach((freq, i) => {
        const osc = ctx.createOscillator();
        osc.type = "sine";
        osc.frequency.value = freq;
        const g = ctx.createGain();
        g.gain.setValueAtTime(0.0001, t + i * 0.08);
        g.gain.exponentialRampToValueAtTime(0.18, t + i * 0.08 + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t + i * 0.08 + 0.5);
        osc.connect(g).connect(master);
        osc.start(t + i * 0.08);
        osc.stop(t + i * 0.08 + 0.55);
      });
    },
    // Number of marbles rolling right now (called every frame).
    rolling(count) {
      if (!ctx || !rollGain) return;
      const target = enabled ? Math.min(0.35, 0.12 * Math.sqrt(count)) : 0;
      rollGain.gain.setTargetAtTime(target, ctx.currentTime, 0.06);
    },
  };
  window.MarbleSound = api;
})();
