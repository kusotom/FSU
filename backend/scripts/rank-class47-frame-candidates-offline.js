#!/usr/bin/env node
'use strict';
const fs=require('fs'); const path=require('path');
function inputs(){const a=[]; for(let i=0;i<process.argv.length;i++) if(process.argv[i]==='--input') a.push(process.argv[i+1]); return a;}
function arg(n,d){const i=process.argv.indexOf(n); return i<0?d:process.argv[i+1];}
function score(c){let s=0; const reasons=[],warnings=[];
 if(c.typeByte==='0x11'){s+=3;reasons.push('+3 typeByte=0x11 matches request family');}
 if(c.classByte==='0x47'){s+=3;reasons.push('+3 classByte=0x47');}
 if(c.flagByte==='0x00'){s+=2;reasons.push('+2 flagByte=0x00 avoids unconfirmed ACK');}
 if(c.tailByte==='0xff'){s+=2;reasons.push('+2 tailByte=0xff');}
 if(c.headerContextCopiedFromRequest){s+=2;reasons.push('+2 copied real request context');}
 if(c.checksumValidUnderNormalModel){s+=2;reasons.push('+2 checksum valid');}
 if(c.seqBytes&&c.seqBytes!=='0000'){s+=2;reasons.push('+2 nonzero/copied seq');}
 if(c.typeByte==='0x1f'){s-=3;warnings.push('-3 ACK-style typeByte with long payload');}
 if(c.flagByte==='0x80'){s-=2;warnings.push('-2 asks for ACK; unconfirmed for 0x47');}
 if(c.typeByte==='0x10'){s-=1;warnings.push('-1 lacks direct evidence');}
 return {score:s,reasons,warnings};}
function main(){const ins=inputs(); if(!ins.length) throw new Error('Use --input <json>; repeatable'); const out=arg('--out','backend/logs/fsu_raw_packets/class47-frame-candidate-ranking.json');
 const analyses=ins.map(input=>{const doc=JSON.parse(fs.readFileSync(input,'utf8')); const candidates=(doc.candidates||[]).map(c=>Object.assign({},c,score(c))).sort((a,b)=>b.score-a.score); return {input,requestProvided:doc.requestProvided,requestSeqBytes:doc.requestSeqBytes,payloadLength:doc.payloadLength,inferredTotalLength:doc.inferredTotalLength,candidates};});
 const result={safety:'offline ranking only; no UDP sent; no ACK sent',conclusion:'Best current offline candidate should be 110047ff with real request seq/context and normal checksum.',analyses,caveats:['Heuristic/static ranking only. Do not send any candidate.','0x47 header not fully confirmed.','1F00_D2FF checksum anomaly unresolved.']};
 fs.mkdirSync(path.dirname(out),{recursive:true}); fs.writeFileSync(out,JSON.stringify(result,null,2)); console.log(JSON.stringify(result,null,2));}
try{main();}catch(e){console.error(JSON.stringify({error:e.message,safety:'no UDP sent'},null,2));process.exit(1);}
