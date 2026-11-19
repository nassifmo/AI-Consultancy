// Run with Node 22 while the evaluator is listening on the configured local port.
const fs = require("node:fs");
const path = require("node:path");
const {spawn} = require("node:child_process");
const project = path.resolve(__dirname, "..");
const port = Number(process.argv[2] || 8771);
const companyUpload = process.argv[3];
const chromePath = process.env.SHIPMENT_CHROME_PATH || "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const profile = path.join(__dirname, "chrome-qa-profile");
const chrome = spawn(chromePath, ["--headless=new", "--remote-debugging-port=9236",
  "--disable-gpu", "--window-size=1440,1300", "--user-data-dir=" + profile, "about:blank"],
  {windowsHide: true, stdio: "ignore"});
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
async function until(test, title, onFailure = () => {}) {
  for (let i = 0; i < 100; i++) {
    try { const value = await test(); if (value) return value; } catch {}
    await pause(180);
  }
  await onFailure();
  throw Error("Timed out: " + title);
}
async function check() {
  const target = await until(async () => (await (await fetch("http://127.0.0.1:9236/json/list")).json())
    .find(item => item.type === "page"), "Chrome tab");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  try {
    let index = 0;
    const waiting = new Map();
    socket.onmessage = event => {
      const message = JSON.parse(event.data);
      const entry = waiting.get(message.id);
      if (entry) {
        waiting.delete(message.id);
        message.error ? entry[1](Error(message.error.message)) : entry[0](message.result);
      }
    };
    const cdp = (method, params = {}) => new Promise((resolve, reject) => {
      const id = ++index;
      waiting.set(id, [resolve, reject]);
      socket.send(JSON.stringify({id, method, params}));
    });
    const js = async expression => (await cdp("Runtime.evaluate", {expression, returnByValue: true})).result?.value;
    const element = (selector, value) => `Array.from(document.querySelectorAll(${JSON.stringify(selector)}))`
      + `.find(e => e.textContent.includes(${JSON.stringify(value)}))`;
    const click = (selector, value) => js(`(${element(selector, value)})?.click()`);
    const see = value => js(`document.body.innerText.includes(${JSON.stringify(value)})`);
    const show = async name => { await click("[role=tab]", name); await pause(1400); };
    const reveal = async (selector, title) => {
      await js(`(${element(selector, title)})?.scrollIntoView({block: 'start'})`);
      await pause(350);
    };
    const shot = async name => fs.writeFileSync(path.join(__dirname, name + ".png"),
      Buffer.from((await cdp("Page.captureScreenshot", {format: "png"})).data, "base64"));
    const debug = async () => console.log((await js("document.body.innerText")).slice(0, 1600));
    const upload = async (selector, filename) => {
      const {root} = await cdp("DOM.getDocument");
      const {nodeId} = await cdp("DOM.querySelector", {nodeId: root.nodeId, selector});
      if (!nodeId) return false;
      await cdp("DOM.setFileInputFiles", {nodeId, files: [filename]});
      return true;
    };
    await cdp("Page.navigate", {url: `http://127.0.0.1:${port}`});
    await until(() => js("!!document.querySelector('[role=combobox]')"), "app controls");
    await js("document.querySelector('[role=combobox]').click()");
    await until(() => js(`Boolean(${element("[role=option]", "Upload an exports ZIP")})`), "upload selector");
    await click("[role=option]", "Upload an exports ZIP");
    await until(() => js("!document.querySelector('[role=option]')"), "committed selection", debug);
    await until(() => upload('[data-testid="stForm"] input[type=file]',
      path.join(project, "meeting_release", "demo_exports.zip")), "file picker ready", debug);
    await until(() => see("demo_exports.zip"), "upload completion", debug);
    await pause(1500);
    await click("button", "Run evaluation");
    await until(() => see("Eligible initial requests"), "uploaded demo analysis", debug);
    if (!await see("1108") || !await see("Upload an exports ZIP")) throw Error("Expected 1,108 eligible roots from upload.");
    await show("Comparison");
    await until(() => see("74.1%"), "demo resolution value");
    await shot("comparison");
    await show("Upgrade value");
    await until(() => see("9.73 USD"), "one-hour break-even value", debug);
    await shot("upgrade-value");
    await reveal("h3", "Decision and next action");
    await until(() => see("Agree on the critical failure limit"), "unset quality limit", debug);
    await js(`(() => {
      const field = Array.from(document.querySelectorAll('[data-testid="stNumberInput"]'))
        .find(item => item.querySelector('label')?.textContent.includes('Maximum critical failure rate'));
      const input = field?.querySelector('input');
      if (!input) throw Error('Decision limit is missing');
      input.scrollIntoView({block: 'center'});
      input.focus();
      input.select();
    })()`);
    await cdp("Input.insertText", {text: "1"});
    await cdp("Input.dispatchKeyEvent", {type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13});
    await cdp("Input.dispatchKeyEvent", {type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13});
    await js("document.activeElement?.blur()");
    await until(() => see("Review failures and retest"), "critical failure recommendation", debug);
    await click("summary", "Decision evidence and downloads");
    await until(async () => await see("Verified critical enquiry IDs") && await see("Download decision brief"),
      "decision evidence and export", debug);
    await shot("decision");
    await show("Costs and settings");
    await shot("costs");
    await show("Enquiry evidence");
    await shot("enquiry");
    await show("Data readiness");
    await shot("readiness");
    await click("summary", "Download and save results");
    await until(() => js(`Boolean(${element("button", "Prepare downloads")})`), "download controls");
    await click("button", "Prepare downloads");
    await until(() => see("Download cost ledger"), "prepared downloadable artifacts", debug);
    await click("summary", "Prepare company files");
    await until(() => js(`Boolean(${element("button", "Preview synthetic company extract")})`), "company example controls");
    if (companyUpload) {
      const profilePath = path.join(project, "pilot", "examples", "renamed_shipment", "profile.json");
      await until(() => upload('input[type=file][accept*=".json"]', profilePath), "company profile picker", debug);
      await until(() => see("profile.json"), "company profile upload", debug);
      await until(() => upload('input[type=file][accept*=".zip"]', companyUpload), "company ZIP picker", debug);
      await until(() => see(path.basename(companyUpload)), "company ZIP upload", debug);
      await pause(1200);
      await click("button", "Preview company mapping");
    } else {
      await click("button", "Preview synthetic company extract");
    }
    await until(() => see("Mapping preview"), "company mapping preview", debug);
    await shot("company-mapping");
    await click("button", "Save and use prepared files");
    await until(() => see("Prepared company files"), "published company extract", debug);
    await click("button", "Run evaluation");
    await until(async () => await see("Prepared company files · 7 days of comparison follow-up")
      && await see("What can we measure from these records?"), "prepared sample readiness", debug);
    await reveal("h3", "What can we measure from these records?");
    await shot("company-readiness");
    await show("Enquiry evidence");
    await until(() => see("WRK-S32-1"), "sample enquiry evidence", debug);
    await until(() => see("What to review and retest"), "case review action", debug);
    await reveal("label", "Find an enquiry");
    await shot("company-enquiry");
    console.log("Verified ZIP analysis, five views, downloads, and the source-mapping-to-evaluation journey.");
  } finally { socket.close(); }
}
check().catch(error => { console.error(error); process.exitCode = 1; }).finally(() => chrome.kill());
