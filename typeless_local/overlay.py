"""Typeless-like floating recording control rendered with WebKit/CSS."""

from __future__ import annotations

import json
from typing import Callable

from AppKit import (
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSStatusWindowLevel,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSObject, NSTimer
from WebKit import WKUserContentController, WKWebView, WKWebViewConfiguration
import objc


ActionCallback = Callable[[str], None]

PANEL_WIDTH = 500
PANEL_HEIGHT = 500
BAR_HEIGHT = 34
IDLE_WIDTH = 40
IDLE_HEIGHT = 6
STARTING_WIDTH = 54
RECORDING_WIDTH = 116
HANDS_FREE_WIDTH = 116
COUNTDOWN_EXTRA_WIDTH = 40


def _hover_kind_for_local_point(
    state: str,
    x: float,
    y: float,
    *,
    has_countdown: bool = False,
) -> str:
    """Return the tooltip target under a panel-local point."""

    bar_bottom = 8.0
    bar_height = float(BAR_HEIGHT)

    if state == "hover":
        bar_width = 70.0
        bar_left = (PANEL_WIDTH - bar_width) / 2.0
        if bar_left <= x <= bar_left + bar_width and bar_bottom <= y <= bar_bottom + bar_height:
            return "idle"
        return ""

    if state not in {"recording", "hands-free"}:
        return ""

    bar_width = float(RECORDING_WIDTH + (COUNTDOWN_EXTRA_WIDTH if has_countdown else 0))
    bar_left = (PANEL_WIDTH - bar_width) / 2.0
    button_top = bar_bottom + 29.0
    button_bottom = bar_bottom + 5.0
    if y < button_bottom or y > button_top:
        return ""

    # Matches the recording-layer flex geometry: 3px centered slack, button margins,
    # 24px circular controls, 38px waveform, and optional 40px countdown block.
    cancel_left = bar_left + 7.0
    cancel_right = cancel_left + 24.0
    finish_left = bar_left + (125.0 if has_countdown else 85.0)
    finish_right = finish_left + 24.0
    if cancel_left <= x <= cancel_right:
        return "cancel"
    if finish_left <= x <= finish_right:
        return "finish"
    return ""


OVERLAY_HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {
    margin: 0;
    width: 100%;
    height: 100%;
    overflow: hidden;
    background: transparent;
    pointer-events: none;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", sans-serif;
  }

  #root {
    position: relative;
    width: 100%;
    height: 100%;
    display: flex;
    align-items: flex-end;
    justify-content: center;
    padding: 8px;
    box-sizing: border-box;
  }

  #bar {
    position: relative;
    width: 40px;
    height: 6px;
    border-radius: 99px;
    background: rgba(128, 128, 128, 0.5);
    opacity: 0;
    overflow: hidden;
    transform: translateZ(0);
    transform-origin: center;
    transition:
      width 200ms cubic-bezier(0.05, 0.6, 0.4, 0.95),
      height 200ms cubic-bezier(0.05, 0.6, 0.4, 0.95),
      opacity 160ms ease,
      transform 200ms cubic-bezier(0.05, 0.6, 0.4, 0.95),
      background-color 160ms ease,
      border-color 160ms ease;
    box-shadow:
      0 2px 4px rgba(0, 0, 0, 0.25),
      0 0 20px rgba(0, 0, 0, 0.15),
      0 25px 30px rgba(0, 0, 0, 0.25);
    border: 0 solid transparent;
    pointer-events: none;
  }

  #bar.visible {
    opacity: 1;
  }

  #bar.active {
    height: 34px;
    background: #000;
    border: 1px solid rgba(255, 255, 255, 0.32);
    box-sizing: border-box;
  }

  #bar.recording {
    width: 116px;
    pointer-events: auto;
  }

  #bar.hands-free {
    width: 116px;
    pointer-events: auto;
  }

  #bar.has-countdown.recording {
    width: 156px;
  }

  #bar.has-countdown.hands-free {
    width: 156px;
  }

  #bar.starting {
    width: 54px;
    height: 12px;
    background: rgba(0, 0, 0, 0.5);
    border: 1px solid rgba(255, 255, 255, 0.22);
  }

  #bar.thinking,
  #bar.error,
  #bar.empty {
    width: 92px;
    height: 34px;
  }

  #bar.error,
  #bar.empty {
    width: 116px;
  }

  #bar.hover {
    width: 70px;
    height: 34px;
    background: #000;
    border: 1px solid rgba(255, 255, 255, 0.32);
    pointer-events: auto;
  }

  #bar.idle-base {
    width: 40px;
    height: 6px;
    background: rgba(128, 128, 128, 0.5);
  }

  #bar.copy-fallback {
    width: 360px;
    height: 120px;
    border-radius: 8px;
    background: rgba(29, 26, 26, 1);
    border: 1px solid rgba(119, 119, 119, 0.30);
    box-sizing: border-box;
    box-shadow:
      0px 25px 30px 0px rgba(0, 0, 0, 0.25),
      0px 0px 20px 0px rgba(0, 0, 0, 0.15);
    backdrop-filter: blur(4px);
    pointer-events: auto;
    overflow: visible;
  }

  .layer {
    position: absolute;
    inset: 0;
    display: none;
    align-items: center;
    justify-content: center;
  }

  #bar.starting .starting-layer,
  #bar.recording .recording-layer,
  #bar.hands-free .recording-layer,
  #bar.thinking .thinking-layer,
  #bar.error .thinking-layer,
  #bar.empty .thinking-layer,
  #bar.copy-fallback .copy-layer,
  #bar.hover .hover-layer {
    display: flex;
  }

  .starting-sweep {
    position: absolute;
    width: 27px;
    height: 27px;
    border-radius: 50%;
    left: -27px;
    top: 50%;
    margin-top: -13.5px;
    background: rgba(242, 241, 240, 0.25);
    filter: blur(10px);
    animation: loadingMove 500ms cubic-bezier(0.42, 0, 0.58, 1) infinite;
  }

  @keyframes loadingMove {
    from { transform: translateX(0); }
    to { transform: translateX(81px); }
  }

  .bars {
    height: 24px;
    width: 38px;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 2px;
    overflow: hidden;
  }

  .bar {
    width: 2px;
    height: 2px;
    min-height: 2px;
    border-radius: 99px;
    background: rgba(255, 255, 255, 1);
    transition: background-color 200ms ease;
    opacity: 1;
  }

  .countdown {
    display: none;
    width: 32px;
    margin-left: 8px;
    color: #fff;
    font-size: 12px;
    font-weight: 400;
    line-height: 1;
    text-align: left;
  }

  #bar.has-countdown .countdown {
    display: block;
  }

  .side-button {
    width: 24px;
    height: 24px;
    border: 0;
    padding: 0;
    border-radius: 50%;
    display: none;
    align-items: center;
    justify-content: center;
    pointer-events: auto;
    cursor: default;
  }

  .control-tooltip {
    position: absolute;
    left: 50%;
    bottom: 52px;
    z-index: 20;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 6px;
    width: max-content;
    max-width: fit-content;
    padding: 6px 10px;
    border-radius: 8px;
    background: rgba(29, 26, 26, 1);
    color: rgba(242, 241, 240, 1);
    font-size: 12px;
    font-weight: 400;
    line-height: 18px;
    white-space: nowrap;
    pointer-events: none;
    opacity: 0;
    transform: translateX(-50%) translateY(4px) scale(0.98);
    transition: opacity 100ms ease, transform 100ms ease;
    will-change: transform, opacity;
    backdrop-filter: blur(4px);
    box-shadow:
      0px 4px 6px -2px rgba(17, 17, 17, 0.03),
      0px 12px 16px -4px rgba(17, 17, 17, 0.10),
      0px 0px 1px 0px rgba(242, 241, 240, 0.55);
    filter: drop-shadow(0px 0px 1px rgba(128, 128, 128, 0.40));
  }

  .control-tooltip.visible {
    opacity: 1;
    transform: translateX(-50%) translateY(0) scale(1);
  }

  .tooltip-key {
    min-width: 18px;
    height: 18px;
    padding: 0 5px;
    border-radius: 5px;
    border: 1px solid rgba(242, 241, 240, 0.20);
    background: rgba(242, 241, 240, 0.08);
    color: rgba(242, 241, 240, 0.82);
    display: none;
    align-items: center;
    justify-content: center;
    box-sizing: border-box;
    font-size: 11px;
    line-height: 16px;
  }

  .control-tooltip.has-key .tooltip-key {
    display: inline-flex;
  }

  #bar.recording .side-button,
  #bar.hands-free .side-button {
    display: flex;
  }

  .cancel {
    margin-left: 4px;
    margin-right: 8px;
    background: rgba(66, 66, 66, 1);
  }

  .finish {
    margin-left: 8px;
    margin-right: 4px;
    background: rgba(255, 255, 255, 1);
  }

  .control-icon {
    width: 18px;
    height: 18px;
    display: block;
    fill: currentColor;
    flex-shrink: 0;
  }

  .cancel .control-icon {
    width: 17px;
    height: 17px;
    color: #fff;
  }

  .finish .control-icon {
    width: 20px;
    height: 20px;
    color: #000;
  }

  .progress {
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 0%;
    background: rgba(242, 241, 240, 0.25);
    border-radius: 99px;
    transition: width 100ms linear;
  }

  .thinking-text {
    position: relative;
    z-index: 1;
    color: rgba(242, 241, 240, 0.56);
    font-size: 14px;
    font-weight: 450;
    line-height: 34px;
    white-space: nowrap;
  }

  #bar.thinking .thinking-text {
    color: transparent;
    background:
      linear-gradient(
        90deg,
        rgba(242, 241, 240, 0.50) 0%,
        rgba(242, 241, 240, 0.92) 45%,
        rgba(242, 241, 240, 0.50) 90%
      );
    background-size: 220% 100%;
    -webkit-background-clip: text;
    background-clip: text;
    animation: textShimmer 2400ms ease-in-out infinite;
  }

  @keyframes textShimmer {
    0% { background-position: 180% 0; }
    100% { background-position: -80% 0; }
  }

  .hover-dots {
    display: flex;
    gap: 2px;
  }

  .hover-dots span {
    width: 2px;
    height: 2px;
    border-radius: 50%;
    background: rgba(128, 128, 128, 1);
  }

  .copy-layer {
    inset: 0;
    padding: 16px;
    box-sizing: border-box;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    gap: 8px;
    color: #fff;
  }

  .copy-header {
    min-height: 20px;
    display: flex;
    align-items: flex-start;
    gap: 8px;
    font-size: 14px;
    font-weight: 500;
    line-height: 20px;
    color: #fff;
  }

  .copy-title-group {
    display: flex;
    align-items: flex-start;
    justify-content: center;
    gap: 8px;
    min-width: 0;
    margin-left: auto;
    margin-right: auto;
  }

  .copy-info-wrap {
    width: 20px;
    height: 20px;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    font-size: 16px;
  }

  .copy-info {
    width: 16px;
    height: 16px;
    color: rgba(101, 138, 255, 1);
    flex-shrink: 0;
  }

  .copy-title {
    min-width: 0;
    color: #fff;
    word-break: break-word;
    white-space: pre-wrap;
  }

  .copy-close {
    width: 20px;
    height: 20px;
    border: 0;
    padding: 0;
    margin: 0;
    background: transparent;
    color: #8f8f8f;
    pointer-events: auto;
    cursor: default;
  }

  .copy-close .control-icon {
    width: 16px;
    height: 16px;
  }

  .copy-text {
    margin: 0;
    min-height: 16px;
    color: #c9c9c9;
    font-size: 12px;
    font-weight: 400;
    line-height: 16px;
    text-align: center;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 5;
    overflow: hidden;
    text-overflow: ellipsis;
    word-break: break-word;
  }

  .copy-footer {
    display: flex;
    align-items: center;
    justify-content: center;
    margin-top: 8px;
  }

  .copy-button {
    min-width: 44px;
    height: 28px;
    border: 1px solid rgba(255, 255, 255, 0.05);
    border-radius: 6px;
    padding: 0 10px;
    background: rgba(255, 255, 255, 0.10);
    color: #fff;
    font-size: 12px;
    font-weight: 500;
    line-height: 26px;
    pointer-events: auto;
    cursor: default;
  }

  .copy-button.copied {
    color: rgba(242, 241, 240, 0.56);
  }

  .copy-button .copied-check {
    width: 12px;
    height: 12px;
    margin-right: 4px;
    color: #2fb344;
    vertical-align: -2px;
  }
</style>
</head>
<body>
  <div id="root">
    <div id="bar">
      <div class="layer starting-layer"><div class="starting-sweep"></div></div>
      <div class="layer recording-layer">
        <button class="side-button cancel" data-action="cancel" data-tooltip="Cancel" aria-label="Cancel"><svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.41-6.3-6.29-6.3 6.29-1.41-1.41L9.17 12 2.88 5.7 4.29 4.29l6.3 6.3 6.3-6.3z"></path></svg></button>
        <div class="bars" id="bars"></div>
        <div class="countdown" id="countdown"></div>
        <button class="side-button finish" data-action="finish" data-tooltip="Finish" data-tooltip-key="F5" aria-label="Finish"><svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"></path></svg></button>
      </div>
      <div class="layer thinking-layer">
        <div class="progress" id="progress"></div>
        <div class="thinking-text" id="message">Thinking</div>
      </div>
      <div class="layer copy-layer">
        <div class="copy-header">
          <div class="copy-title-group">
            <div class="copy-info-wrap"><svg class="copy-info" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M11 17h2v-6h-2zm0-8h2V7h-2zm1-7a10 10 0 1 0 0 20 10 10 0 0 0 0-20m0 18a8 8 0 1 1 0-16 8 8 0 0 1 0 16"></path></svg></div>
            <div class="copy-title">Copy last transcript</div>
          </div>
          <button class="copy-close" data-action="dismiss"><svg class="control-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M18.3 5.71 12 12l6.3 6.29-1.41 1.41-6.3-6.29-6.3 6.29-1.41-1.41L9.17 12 2.88 5.7 4.29 4.29l6.3 6.3 6.3-6.3z"></path></svg></button>
        </div>
        <div class="copy-text" id="copyText"></div>
        <div class="copy-footer"><button class="copy-button" id="copyButton" data-action="copy-fallback">Copy</button></div>
      </div>
      <div class="layer hover-layer">
        <div class="hover-dots"><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span><span></span></div>
      </div>
    </div>
    <div class="control-tooltip" id="controlTooltip" role="tooltip"><span id="tooltipText"></span><span class="tooltip-key" id="tooltipKey">F5</span></div>
  </div>
<script>
  const root = document.getElementById("root");
  const bar = document.getElementById("bar");
  const bars = document.getElementById("bars");
  const progress = document.getElementById("progress");
  const message = document.getElementById("message");
  const countdown = document.getElementById("countdown");
  const copyText = document.getElementById("copyText");
  const copyButton = document.getElementById("copyButton");
  const controlTooltip = document.getElementById("controlTooltip");
  const tooltipText = document.getElementById("tooltipText");
  const tooltipKey = document.getElementById("tooltipKey");
  const barEls = [];
  for (let i = 0; i < 10; i += 1) {
    const el = document.createElement("div");
    el.className = "bar";
    bars.appendChild(el);
    barEls.push(el);
  }

  let state = "idle-hidden";
  const MIN_HEIGHT = 2;
  const MAX_HEIGHT = 18;
  const MAX_PULSE_HEIGHT = 18;
  const NOISE_THRESHOLD = 0.03;
  const VOICE_THRESHOLD = 0.12;
  const DIFFUSION_DELAY = 80;
  const INPUT_RESPONSE_GAIN = 0.60;
  const TRIGGER_PROBABILITY_GAIN = 0.60;
  const TRIGGER_MAX_PROBABILITY = 0.32;
  const PULSE_TRIGGER_THRESHOLD = NOISE_THRESHOLD * 0.85;
  const SILENCE_DECAY_THRESHOLD = NOISE_THRESHOLD * 1.15;
  let lastInputLevel = 0;
  let smoothedHeight = 3;
  let lastPulseAt = 0;
  let volumeBuffer = [];
  let pendingPulses = [];
  let sideTimers = [];
  let barVolumes = new Array(10).fill(MIN_HEIGHT);
  let barAges = new Array(10).fill(0);

  function setClass(nextState, hasCountdown) {
    bar.className = "";
    if (nextState !== "idle-hidden") bar.classList.add("visible");
    if (["recording", "hands-free", "thinking", "error", "empty", "hover", "copy-fallback"].includes(nextState)) {
      bar.classList.add("active");
    }
    if (hasCountdown) bar.classList.add("has-countdown");
    if (nextState !== "idle-hidden") bar.classList.add(nextState);
  }

  window.setOverlayState = function(payload) {
    const previousState = state;
    state = payload.state || "idle-hidden";
    message.textContent = payload.message || "Thinking";
    progress.style.width = `${Math.max(0, Math.min(1, payload.progress || 0)) * 100}%`;
    countdown.textContent = payload.countdown || "";
    copyText.textContent = payload.transcript ? `“${payload.transcript}”` : "";
    setCopyButton(Boolean(payload.copied));
    setClass(state, Boolean(payload.countdown));
    if (previousState !== state && !["recording", "hands-free", "hover"].includes(state)) {
      hideControlTooltip();
    }
    if (state !== "recording" && state !== "hands-free") {
      resetBars();
    }
  };

  window.setAudioLevel = function(level) {
    const incoming = Math.max(0, Math.min(1, Number(level) || 0));
    const active = state === "recording" || state === "hands-free";
    if (!active) {
      resetBars();
      return;
    }

    const now = performance.now();
    processPendingPulses(now);
    pushVolume(incoming);
    const averaged = Math.max(0, Math.min(1, averageVolume() * INPUT_RESPONSE_GAIN));
    const mappedHeight = mapLevelToHeight(averaged);
    smoothedHeight = smoothedHeight * 0.15 + mappedHeight * 0.85;
    maybeQueuePulse(averaged, smoothedHeight, now);
    processPendingPulses(now);
    decayBars(averaged);
    renderBars();
    lastInputLevel = incoming;
  };

  document.addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (!action) return;
    event.preventDefault();
    hideControlTooltip();
    if (window.webkit?.messageHandlers?.overlayAction) {
      window.webkit.messageHandlers.overlayAction.postMessage(action);
    }
  });

  function showControlTooltip(target, text, keyText) {
    if (!target || !text) return;
    const rootRect = root.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const centerX = targetRect.left - rootRect.left + targetRect.width / 2;
    const bottom = rootRect.bottom - targetRect.top + 10;
    tooltipText.textContent = text;
    tooltipKey.textContent = keyText || "";
    controlTooltip.classList.toggle("has-key", Boolean(keyText));
    controlTooltip.style.left = `${centerX}px`;
    controlTooltip.style.bottom = `${bottom}px`;
    controlTooltip.classList.add("visible");
    controlTooltip.dataset.target = target.dataset.tooltip || "bar";
  }

  function hideControlTooltip() {
    controlTooltip.classList.remove("visible", "has-key");
    controlTooltip.dataset.target = "";
  }

  document.querySelectorAll("[data-tooltip]").forEach((target) => {
    const show = () => showControlTooltip(target, target.dataset.tooltip, target.dataset.tooltipKey || "");
    target.addEventListener("mouseenter", show);
    target.addEventListener("mouseover", show);
    target.addEventListener("pointerenter", show);
    target.addEventListener("focus", show);
    target.addEventListener("mouseleave", hideControlTooltip);
    target.addEventListener("pointerleave", hideControlTooltip);
    target.addEventListener("blur", hideControlTooltip);
  });

  function updateTooltipFromPointer(event) {
    const hovered = document.elementFromPoint(event.clientX, event.clientY)?.closest("[data-tooltip]");
    if (hovered) {
      showControlTooltip(hovered, hovered.dataset.tooltip, hovered.dataset.tooltipKey || "");
      return;
    }
    if (state === "hover" && bar.contains(event.target)) {
      showControlTooltip(bar, "Click to start dictating", "");
      return;
    }
    hideControlTooltip();
  }

  bar.addEventListener("mousemove", updateTooltipFromPointer);
  bar.addEventListener("pointermove", updateTooltipFromPointer);

  window.setPointerTooltip = function(kind) {
    if (kind === "cancel") {
      const target = document.querySelector('[data-action="cancel"]');
      showControlTooltip(target, target?.dataset.tooltip, target?.dataset.tooltipKey || "");
      return;
    }
    if (kind === "finish") {
      const target = document.querySelector('[data-action="finish"]');
      showControlTooltip(target, target?.dataset.tooltip, target?.dataset.tooltipKey || "");
      return;
    }
    if (kind === "idle") {
      showControlTooltip(bar, "Click to start dictating", "");
      return;
    }
    hideControlTooltip();
  };

  bar.addEventListener("mouseenter", (event) => {
    if (event.target.closest("[data-tooltip]")) return;
    if (state === "hover") {
      showControlTooltip(bar, "Click to start dictating", "");
    }
  });

  bar.addEventListener("mouseleave", (event) => {
    if (!bar.contains(event.relatedTarget)) {
      hideControlTooltip();
    }
  });

  function resetBars() {
    sideTimers.forEach((timer) => clearTimeout(timer));
    barVolumes = barVolumes.map(() => MIN_HEIGHT);
    barAges = barAges.map(() => 0);
    volumeBuffer = [];
    pendingPulses = [];
    sideTimers = [];
    smoothedHeight = 3;
    lastInputLevel = 0;
    lastPulseAt = 0;
    renderBars();
  }

  function pushVolume(level) {
    volumeBuffer.push(level);
    if (volumeBuffer.length > 3) volumeBuffer.shift();
  }

  function averageVolume() {
    if (volumeBuffer.length === 0) return 0;
    return volumeBuffer.reduce((sum, value) => sum + value, 0) / volumeBuffer.length;
  }

  function randomBetween(min, max) {
    return min + Math.random() * (max - min);
  }

  function decayBars(level) {
    const count = barVolumes.length;
    const center = Math.floor(count / 2);
    const isQuietInput = level < SILENCE_DECAY_THRESHOLD;
    for (let i = 0; i < barEls.length; i += 1) {
      if (barVolumes[i] <= MIN_HEIGHT) continue;
      const increment = Math.random() > 0.45 ? 1 : Math.random() > 0.88 ? 2 : 0;
      const age = barAges[i] + increment + (isQuietInput ? 1 : 0);
      const maxAge = 50 + Math.floor(Math.random() * 15);
      const baseDecay = isQuietInput ? randomBetween(0.94, 0.975) : randomBetween(0.97, 0.99);
      const positionFactor = 1 + Math.abs(i - center) / count * 0.3;
      const effectiveDecay = Math.max(isQuietInput ? 0.90 : 0.93, baseDecay / positionFactor);
      const decayed = barVolumes[i] * Math.pow(effectiveDecay, age / 12);
      const next = Math.max(MIN_HEIGHT, Math.round(decayed * randomBetween(0.95, 1.05)));
      if (age > maxAge || next <= MIN_HEIGHT) {
        barVolumes[i] = MIN_HEIGHT;
        barAges[i] = 0;
      } else {
        barVolumes[i] = next;
        barAges[i] = age;
      }
    }
  }

  function mapLevelToHeight(level) {
    let response;
    if (level < NOISE_THRESHOLD) {
      response = 0.12 + (level / NOISE_THRESHOLD) * 0.18 + Math.random() * 0.03;
    } else if (level < VOICE_THRESHOLD) {
      const t = (level - NOISE_THRESHOLD) / (VOICE_THRESHOLD - NOISE_THRESHOLD);
      response = 0.32 + t * 0.38 + (Math.random() * 2 - 1) * 0.10;
      response = Math.max(0.28, Math.min(0.75, response));
    } else {
      const t = Math.pow((level - VOICE_THRESHOLD) / (1 - VOICE_THRESHOLD), 0.25);
      const normalized = (level - VOICE_THRESHOLD) / (1 - VOICE_THRESHOLD);
      const randomFactor = Math.max(0.15, 0.25 * normalized);
      let voice = Math.max(0, Math.min(1, t + (Math.random() * 2 - 1) * randomFactor));
      if (normalized > 0.4) {
        voice = Math.min(1, voice * (1.4 + (Math.random() * 0.4 - 0.2)));
      }
      response = 0.55 + 0.4 * voice + (Math.random() * 2 - 1) * 0.10;
      response = Math.max(0.45, Math.min(1, response));
    }
    response = Math.max(0.12, Math.min(1, response));
    return Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, MIN_HEIGHT + Math.round((MAX_HEIGHT - MIN_HEIGHT) * response)));
  }

  function maybeQueuePulse(level, height, now) {
    if (level <= PULSE_TRIGGER_THRESHOLD) return;
    if (now - lastPulseAt < 130) return;
    const probability = Math.min(TRIGGER_MAX_PROBABILITY, level * TRIGGER_PROBABILITY_GAIN);
    if (Math.random() > probability) return;
    pendingPulses.push({
      timestamp: now,
      volume: Math.max(MIN_HEIGHT, Math.min(MAX_PULSE_HEIGHT, Math.round(height * randomBetween(0.95, 1.15)))),
    });
    lastPulseAt = now;
  }

  function processPendingPulses(now) {
    const next = [];
    for (const pulse of pendingPulses) {
      if (now - pulse.timestamp >= DIFFUSION_DELAY) {
        applyPulse(pulse, now);
      } else {
        next.push(pulse);
      }
    }
    pendingPulses = next;
  }

  function applyPulse(pulse, now) {
    void now;
    const count = barVolumes.length;
    const baseCenter = Math.floor(count / 2);
    const centerOffset = Math.floor((Math.random() - 0.5) * Math.min(count * 0.15, 3));
    const center = Math.max(0, Math.min(count - 1, baseCenter + centerOffset));
    const centerVolume = Math.round(pulse.volume * randomBetween(0.95, 1.05));
    setBar(center, centerVolume, 0);

    const leftSpan = center;
    const rightSpan = count - 1 - center;
    const maxSpan = Math.max(leftSpan, rightSpan);
    for (let distance = 1; distance <= maxSpan; distance += 1) {
      const leftIndex = center - distance;
      const rightIndex = center + distance;
      const leftDecay = Math.max(0.12, 1 - distance / Math.max(leftSpan, 1) * (0.65 + Math.random() * 0.08));
      const rightDecay = Math.max(0.12, 1 - distance / Math.max(rightSpan, 1) * (0.65 + Math.random() * 0.08));
      const leftVolume = Math.max(MIN_HEIGHT, Math.round(pulse.volume * leftDecay * randomBetween(0.9, 1.1)));
      const rightVolume = Math.max(MIN_HEIGHT, Math.round(pulse.volume * rightDecay * randomBetween(0.9, 1.1)));
      const leftDelay = distance * DIFFUSION_DELAY * randomBetween(0.15, 0.20) + Math.random() * 15;
      const rightDelay = distance * DIFFUSION_DELAY * randomBetween(0.15, 0.20) + Math.random() * 15;
      if (leftIndex >= 0) {
        scheduleSideUpdate(leftIndex, leftVolume, leftDelay);
      }
      if (rightIndex < count) {
        scheduleSideUpdate(rightIndex, rightVolume, rightDelay);
      }
    }
    renderBars();
  }

  function setBar(index, height, age) {
    barVolumes[index] = Math.max(MIN_HEIGHT, Math.min(MAX_PULSE_HEIGHT, Math.round(height)));
    barAges[index] = age;
  }

  function scheduleSideUpdate(index, height, delay) {
    const timer = setTimeout(() => {
      sideTimers = sideTimers.filter((value) => value !== timer);
      if (state !== "recording" && state !== "hands-free") return;
      blendBar(index, height);
      renderBars();
    }, delay);
    sideTimers.push(timer);
  }

  function blendBar(index, height) {
    const target = Math.max(MIN_HEIGHT, Math.min(MAX_PULSE_HEIGHT, Math.round(height)));
    const current = barVolumes[index] || MIN_HEIGHT;
    const blend = randomBetween(0.65, 0.75);
    barVolumes[index] = Math.max(target, Math.round(current * (1 - blend) + target * blend));
    barAges[index] = Math.floor(Math.random() * 2);
  }

  function renderBars() {
    const active = state === "recording" || state === "hands-free";
    for (let i = 0; i < barEls.length; i += 1) {
      const height = active ? Math.max(MIN_HEIGHT, Math.min(MAX_PULSE_HEIGHT, barVolumes[i])) : MIN_HEIGHT;
      barEls[i].style.height = `${height.toFixed(2)}px`;
      barEls[i].style.opacity = active && height > MIN_HEIGHT + 0.2 ? "1" : "0.5";
    }
  }

  function setCopyButton(copied) {
    copyButton.classList.toggle("copied", copied);
    if (copied) {
      copyButton.innerHTML = '<svg class="copied-check" viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" d="M9 16.17 4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"></path></svg>Copied';
    } else {
      copyButton.textContent = "Copy";
    }
  }
  window.setOverlayState({ state: "idle-hidden" });
</script>
</body>
</html>
"""


class OverlayActionHandler(NSObject):
    """Bridge button clicks from WKWebView back to Python."""

    def initWithOwner_(self, owner):
        self = objc.super(OverlayActionHandler, self).init()
        if self is None:
            return None
        self.owner = owner
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message) -> None:
        del controller
        callback = getattr(self.owner, "action_callback", None)
        if callback is not None:
            callback(str(message.body()))


class FloatingOverlay(NSObject):
    """Owns the bottom-centered non-activating overlay panel."""

    def init(self):
        self = objc.super(FloatingOverlay, self).init()
        if self is None:
            return None
        self.panel = None
        self.webview = None
        self._handler = None
        self._state = "idle-hidden"
        self._has_countdown = False
        self._hover_timer = None
        self._hover_kind = ""
        self.action_callback = None
        return self

    @objc.python_method
    def set_action_callback(self, callback: ActionCallback | None) -> None:
        self.action_callback = callback

    @objc.python_method
    def setup(self) -> None:
        frame = NSScreen.mainScreen().visibleFrame()
        rect = self._panel_rect(frame)
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            rect,
            NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.setOpaque_(False)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setLevel_(NSStatusWindowLevel)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setAcceptsMouseMovedEvents_(True)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        controller = WKUserContentController.alloc().init()
        self._handler = OverlayActionHandler.alloc().initWithOwner_(self)
        controller.addScriptMessageHandler_name_(self._handler, "overlayAction")
        config = WKWebViewConfiguration.alloc().init()
        config.setUserContentController_(controller)

        self.webview = WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, PANEL_WIDTH, PANEL_HEIGHT),
            config,
        )
        self.webview.setOpaque_(False)
        self.webview.setBackgroundColor_(NSColor.clearColor())
        self.webview.setValue_forKey_(False, "drawsBackground")
        self.webview.loadHTMLString_baseURL_(OVERLAY_HTML, None)
        self.panel.setContentView_(self.webview)
        self.panel.orderFrontRegardless()
        self.hide()

    @objc.python_method
    def hide(self) -> None:
        self._state = "idle-hidden"
        self._set_mouse_events(False)
        self._send_state("idle-hidden")
        if self.panel is not None:
            self.panel.setAlphaValue_(0.0)

    @objc.python_method
    def show_hover(self) -> None:
        self._send_state("hover")

    @objc.python_method
    def show_idle_base(self) -> None:
        self._send_state("idle-base")

    @objc.python_method
    def show_starting(self) -> None:
        self._send_state("starting")

    @objc.python_method
    def show_recording(self, hands_free: bool = False, countdown_text: str = "") -> None:
        self._send_state("hands-free" if hands_free else "recording", countdown=countdown_text)

    @objc.python_method
    def show_thinking(self, progress: float = 0.0, message: str = "Thinking") -> None:
        self._send_state("thinking", message=message, progress=progress)

    @objc.python_method
    def show_error(self, message: str) -> None:
        self._send_state("error", message=message, progress=1.0)

    @objc.python_method
    def show_empty(self) -> None:
        self._send_state("empty", message="No speech", progress=1.0)

    @objc.python_method
    def show_copy_fallback(self, transcript: str, copied: bool = False) -> None:
        self._send_state("copy-fallback", transcript=transcript, copied=copied)

    @objc.python_method
    def update_level(self, level: float) -> None:
        self._eval(f"window.setAudioLevel({float(level):.5f});")

    @objc.python_method
    def resizeToWidth_(self, width: int) -> None:
        del width

    @objc.python_method
    def _send_state(
        self,
        state: str,
        message: str = "",
        progress: float = 0.0,
        countdown: str = "",
        transcript: str = "",
        copied: bool = False,
    ) -> None:
        self._state = state
        self._has_countdown = bool(countdown)
        self._set_mouse_events(state in {"idle-base", "hover", "recording", "hands-free", "copy-fallback"})
        if self.panel is not None:
            self.panel.setAlphaValue_(0.0 if state == "idle-hidden" else 1.0)
            self.panel.orderFrontRegardless()
        payload = json.dumps(
            {
                "state": state,
                "message": message,
                "progress": progress,
                "countdown": countdown,
                "transcript": transcript,
                "copied": copied,
            }
        )
        self._eval(f"window.setOverlayState({payload});")
        if state in {"hover", "recording", "hands-free"}:
            self._start_hover_tracking()
        else:
            self._stop_hover_tracking()

    @objc.python_method
    def _eval(self, script: str) -> None:
        if self.webview is not None:
            self.webview.evaluateJavaScript_completionHandler_(script, None)

    @objc.python_method
    def _set_mouse_events(self, enabled: bool) -> None:
        if self.panel is not None:
            self.panel.setIgnoresMouseEvents_(not enabled)

    @objc.python_method
    def _start_hover_tracking(self) -> None:
        if self._hover_timer is not None:
            return
        self._hover_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.05,
            self,
            "pollHover:",
            None,
            True,
        )

    @objc.python_method
    def _stop_hover_tracking(self) -> None:
        timer = getattr(self, "_hover_timer", None)
        if timer is not None:
            timer.invalidate()
            self._hover_timer = None
        self._set_pointer_tooltip("")

    def pollHover_(self, timer) -> None:
        del timer
        if self.panel is None:
            self._set_pointer_tooltip("")
            return
        frame = self.panel.frame()
        point = NSEvent.mouseLocation()
        local_x = float(point.x - frame.origin.x)
        local_y = float(point.y - frame.origin.y)
        if local_x < 0 or local_y < 0 or local_x > PANEL_WIDTH or local_y > PANEL_HEIGHT:
            self._set_pointer_tooltip("")
            return
        kind = _hover_kind_for_local_point(
            self._state,
            local_x,
            local_y,
            has_countdown=bool(getattr(self, "_has_countdown", False)),
        )
        self._set_pointer_tooltip(kind)

    @objc.python_method
    def _set_pointer_tooltip(self, kind: str) -> None:
        kind = kind or ""
        if kind == getattr(self, "_hover_kind", ""):
            return
        self._hover_kind = kind
        self._eval(f"window.setPointerTooltip({json.dumps(kind)});")

    @objc.python_method
    def _panel_rect(self, frame):
        return NSMakeRect(
            frame.origin.x + (frame.size.width - PANEL_WIDTH) / 2,
            frame.origin.y,
            PANEL_WIDTH,
            PANEL_HEIGHT,
        )
