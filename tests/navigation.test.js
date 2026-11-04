'use strict';

const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {test} = require('node:test');

function navigationFixture(hidden = ['s002', 's004']) {
  const sent = [];
  const frame = {contentWindow: {postMessage: (message) => sent.push(message)}};
  const ui = {
    slide: 's001',
    state: {slides: ['s001', 's002', 's003', 's004', 's005']},
    showHiddenInNavigation: false,
    variant: 'standard',
    mainMode: 'slides',
    previewUrl: '/slides.html',
    selectedIndex: 0,
  };
  const context = {
    ui,
    currentVariant: () => ({hidden_slides: hidden}),
    hasPresentation: () => true,
    $: (id) => id === 'slide-iframe' ? frame : {disabled:false,hidden:false,classList:{toggle:()=>{}},setAttribute:()=>{},textContent:'',title:''},
    layoutSlidePreview: () => {},
    rememberChoices: () => {},
    updateSlideUI: () => {},
  };
  vm.createContext(context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '..', 'static', 'navigation.js'), 'utf8'), context);
  context.updateSlideUI = () => {};
  return {context, ui, sent, frame};
}

test('hidden slides are skipped in the direction of preview navigation', () => {
  const {context, ui, frame, sent} = navigationFixture();
  context.chooseSlide('s005');
  context.handlePreviewMessage({source: frame.contentWindow, data:{type:'studio-slide',id:'s004',url:'/slides.html'}});
  assert.equal(ui.slide, 's003');
  assert.equal(sent.at(-1).id, 's003');
  context.handlePreviewMessage({source: frame.contentWindow, data:{type:'studio-slide',id:'s002',url:'/slides.html'}});
  assert.equal(ui.slide, 's001');
  context.handlePreviewMessage({source: frame.contentWindow, data:{type:'studio-slide',id:'s002',url:'/slides.html'}});
  assert.equal(ui.slide, 's003');
  context.handlePreviewMessage({source: frame.contentWindow, data:{type:'studio-slide',id:'s004',url:'/slides.html'}});
  assert.equal(ui.slide, 's005');
});

test('multiple adjacent hidden slides and list boundaries', () => {
  const {context, ui} = navigationFixture(['s002','s003','s004']);
  context.chooseSlide('s005');
  context.chooseSlide('s004');
  assert.equal(ui.slide, 's001');
  context.chooseSlide('s003');
  assert.equal(ui.slide, 's005');
  context.chooseSlide('invalid');
  assert.equal(ui.slide, 's001');
});

test('including hidden slides allows direct navigation', () => {
  const {context, ui} = navigationFixture();
  ui.showHiddenInNavigation = true;
  context.chooseSlide('s002');
  assert.equal(ui.slide, 's002');
});

test('previous and next toolbar navigation use visible slides only', () => {
  const {context, ui, sent} = navigationFixture();
  context.chooseSlide('s003');
  context.goSlide(-1);
  assert.equal(ui.slide,'s001');
  context.goSlide(1);
  assert.equal(ui.slide,'s003');
  assert.ok(sent.some((message) => message.type === 'studio-goto' && message.id === 's001'));
});

test('unrelated iframe messages do not change selection', () => {
  const {context, ui} = navigationFixture();
  context.handlePreviewMessage({source: {}, data:{type:'studio-slide',id:'s003',url:'/slides.html'}});
  context.handlePreviewMessage({source: context.$('slide-iframe').contentWindow, data:{type:'studio-slide',id:'s003',url:'/wrong.html'}});
  assert.equal(ui.slide,'s001');
});
