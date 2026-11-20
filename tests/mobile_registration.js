const frame = document.querySelector('iframe')
const doc = () => frame.contentDocument
const el = selector => doc().querySelector(selector)
const all = selector => [...doc().querySelectorAll(selector)]
const texts = selector => all(selector).map(node => node.textContent)
const byText = (selector, text) => all(selector).find(node => node.textContent.trim() === text)
function equal(actual, expected) {
  if (JSON.stringify(actual) !== JSON.stringify(expected)) throw Error(`Expected ${JSON.stringify(expected)}; got ${JSON.stringify(actual)}`)
}
async function until(read, description) {
  const end = Date.now() + 10000
  while (Date.now() < end) {
    const value = read()
    if (value) return value
    await new Promise(resolve => setTimeout(resolve, 30))
  }
  throw Error(`Timed out: ${description}. ${el('[role=alert]')?.textContent || ''}`)
}
async function click(selector, text) {
  const node = await until(() => text ? byText(selector, text) : el(selector), text || selector)
  equal(Boolean(node.disabled), false)
  node.scrollIntoView({block:'center'})
  node.click()
  await Promise.resolve()
}
function fill(value) {
  const input = el('#message')
  input.value = value
  input.dispatchEvent(new Event('input', {bubbles:true}))
}
async function send(value) {
  if (value !== undefined) { fill(value); await Promise.resolve() }
  const body = el('#message').value
  await click('.composer-foot button', '发送')
  await until(() => texts('.message.user:not(.draft-bubble) p').includes(body) && !el('.working'), 'saved: ' + body)
}
async function contact(name) {
  await click('.roster-row b', name)
  await until(() => el('.thread-head b')?.textContent === name, name + ' private thread')
}
async function reload() {
  const ready = new Promise(resolve => frame.addEventListener('load', resolve, {once:true}))
  frame.contentWindow.location.reload()
  await ready
}
async function fields(project, city, submitted) {
  await until(() => el('.registration-panel'), 'registration panel')
  equal(texts('.registration-panel li .stage-pill'), [project, city])
  equal(el('.registration-panel > p:last-child').textContent, '已提交项：' + submitted)
}

async function run() {
  const mixed = '项目经历可以给，所在城市先不提供', question = '登记资料用来做什么？'
  const correction = '所在城市可以给。算了，所在城市先不提供'
  const sent = '我提交的项目经历：虚构项目 A', refused = '我拒绝继续提供项目经历'
  await click('button', '进入训练')
  await until(() => el('#message'), 'composer')
  equal(frame.contentWindow.innerWidth, 390)
  equal(frame.contentWindow.innerHeight, 844)
  await send('你好')
  await contact('陈浩')
  await click('button', '我对你介绍的 Python 实习感兴趣。')
  await send()
  await fields('未表态','未表态','无')

  fill('甲'.repeat(599))
  await click('button', question)
  equal(el('#message').value, '甲'.repeat(599))
  fill('')
  for (const [field, choice] of [['项目经历','同意提供'], ['所在城市','暂缓']]) {
    await click('summary', `拟写${field}的回应`)
    await click('.registration-panel details[open] button', choice)
    await click('summary', `拟写${field}的回应`)
  }
  equal(el('#message').value, mixed)
  await click('button', question)
  equal(el('#message').value, mixed + '\n' + question)
  equal(doc().activeElement === el('#message'), true)
  equal(all('.message.user').length, 1)
  const edited = mixed + '\n我还想问：' + question
  await send(edited)
  await fields('同意提供','暂缓','无')

  for (const name of ['林悦','王宇']) {
    await contact(name)
    equal(el('.registration-panel'), null)
    equal(texts('.message p').includes(edited), false)
  }
  await reload()
  await until(() => byText('.message.user p', '你好'), 'restored greeting')
  await contact('陈浩')
  await reload()
  await fields('同意提供','暂缓','无')
  equal(texts('.message.user p').filter(t => t === edited).length, 1)
  await send(correction)
  await send(sent + '。' + refused)
  await fields('拒绝','暂缓','项目经历')
  await click('button', '我不参与预登记。')
  await send()
  equal(all('.registration-panel summary').length, 0)
  await reload()
  await fields('拒绝','暂缓','项目经历')
  equal(all('.composer .small-prompts button').length, 0)
  await send('我改主意了，现在想登记')
  await fields('拒绝','暂缓','项目经历')
  equal(all('.registration-panel summary').length, 2)

  await click('button', '作出决策')
  await click('dialog .choice b', '仅提交必要资料')
  equal(el('dialog #reason').value, '')
  await click('dialog .cite-list summary')
  const greeting = all('.cite-list label').find(l => l.textContent === '王宇私聊 · 你你好')
  greeting.querySelector('input').click()
  equal(all('.cite-list :checked').length, 1)
  await click('button', '提交并查看复盘')
  await until(() => byText('h1','本场训练复盘'), 'archived review')
  await reload()
  await until(() => byText('h2','仅提交必要资料'), 'restored decision')
  const review = el('[aria-label="登记复盘"]')
  equal(review.querySelector('h3').textContent, '已提交项：项目经历')
  equal(texts('[aria-label="登记复盘"] li'), ['项目经历 · 拒绝','所在城市 · 暂缓'])
  for (const [first,last] of [['所在城市可以给','所在城市先不提供'], [sent,refused]]) {
    const turn = byText('[aria-label="登记复盘"] blockquote', first).closest('article')
    equal([...turn.querySelectorAll(':scope > div > blockquote')].map(e => e.textContent), [first,last])
  }
  const decision = byText('h3','决策合理性').closest('article')
  equal(decision.querySelector('.dim-status').textContent, '证据不足')
  equal([...decision.querySelectorAll('blockquote')].map(e => e.textContent), ['你好'])
  equal(doc().documentElement.scrollWidth <= frame.contentWindow.innerWidth, true)
  decision.querySelector('a').click()
  await until(() => byText('.message.highlight p', '你好'), 'link to original greeting')
  equal(el('#message'), null)
}

let result
try { await run(); result = {ok:true} }
catch (error) { result = {ok:false, error:String(error.stack || error)} }
document.querySelector('output').textContent = JSON.stringify(result)
await fetch('./result', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(result)})
