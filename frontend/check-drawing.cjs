const fs = require('node:fs');
const vm = require('node:vm');
const ts = require('typescript');
const assert = require('node:assert/strict');
let cursor = 0, states = [], effects = [], pending = [];
const strokes = [];
const ctx = new Proxy({}, { get: (_, key) => (...args) => strokes.push(key) });
const canvas = { width:800, height:500, getContext:()=>ctx, getBoundingClientRect:()=>({left:0,top:0,width:800,height:500}), setPointerCapture(){}, toDataURL:()=> 'new-drawing' };
const react = {
 useRef(initial) { const i=cursor++; return states[i] ||= {current: initial === null ? canvas : initial}; },
 useState(initial) { const i=cursor++; if (!(i in states)) states[i]=initial; return [states[i], value=>{states[i]=typeof value==='function'?value(states[i]):value;}]; },
 useEffect(effect) { const i=cursor++; if (!(i in states)) {states[i]=true;effects.push(effect);} }
};
const code=ts.transpileModule(fs.readFileSync(__dirname + '/src/Drawing.tsx','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX}}).outputText;
const jsx = (type, props)=>({type,props});
const sandbox={exports:{}, require(name){if(name==='react')return react;if(name==='react/jsx-runtime')return {jsx,jsxs:jsx};throw Error(name);}, Image:class{ set src(value){pending.push(this);} }};
vm.runInNewContext(code,sandbox);
let value='saved-drawing';
function render(){cursor=0;const tree=sandbox.exports.Drawing({value,onChange:v=>value=v,label:'Smoke'});for(const fn of effects.splice(0))fn();return tree;}
function all(node){return !node || typeof node !== 'object' ? [] : [node,...[node.props?.children].flat(Infinity).flatMap(all)];}
function button(tree,text){return all(tree).find(n=>n.type==='button'&&n.props.children===text);}
let tree=render();pending.shift().onload();tree=render();button(tree,'清空').props.onClick();tree=render();button(tree,'撤销').props.onClick();tree=render();
const drawing=all(tree).find(n=>n.type==='canvas');
const before=strokes.length;
drawing.props.onPointerDown({button:0,preventDefault(){},currentTarget:canvas,pointerId:1,clientX:20,clientY:20});
assert.equal(strokes.length,before,'pending undo restoration must reject new drawing instead of later overwriting it');
assert.equal(drawing.props['aria-busy'],true,'pending undo must advertise busy state');
pending.shift().onload();tree=render();assert.equal(all(tree).find(n=>n.type==='canvas').props['aria-busy'],false);
console.log('PASS: undo restoration blocks edits until decoded; busy clears after decode');
