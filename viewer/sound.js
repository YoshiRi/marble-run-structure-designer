// Synthesized marble sounds (Web Audio, no sound files): a wooden "tock"
// when a marble lands after a fall, a soft rolling rumble while marbles roll,
// a low clack for the seesaw and a chime at an exit. The audio context starts
// on the first user gesture (browsers block sound before one).
(function () {
  "use strict";

  const STORE = "marble-run-sound-v1";
  let ctx = null;
  let master = null;
  let rollGain = null;
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
      startRumble();
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

  // Continuous filtered noise; its gain follows the number of rolling marbles.
  function startRumble() {
    const source = ctx.createBufferSource();
    source.buffer = noiseBuffer(2);
    source.loop = true;
    const band = ctx.createBiquadFilter();
    band.type = "bandpass";
    band.frequency.value = 900;
    band.Q.value = 0.8;
    const low = ctx.createBiquadFilter();
    low.type = "lowpass";
    low.frequency.value = 2200;
    rollGain = ctx.createGain();
    rollGain.gain.value = 0;
    source.connect(band).connect(low).connect(rollGain).connect(master);
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
    // A marble lands after falling `dropCm`.
    land(dropCm) {
      const strength = Math.min(1, 0.35 + dropCm / 25);
      knock(700 + Math.random() * 250, strength, 0.12);
    },
    seesaw() { knock(260, 0.9, 0.22); },
    exit() {
      if (!ensure()) return;
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
