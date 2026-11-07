const assert=require('node:assert/strict');
const crypto=require('node:crypto');
const {publishReviewedSourceWithConnector}=require('./source_publication_connector.cjs');
const head='a'.repeat(40),base='b'.repeat(40),tree='c'.repeat(40),commit='d'.repeat(40);
const gitsha=data=>crypto.createHash('sha1').update(Buffer.from('blob '+data.length+'\0')).update(data).digest('hex');
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
const objects={'000000.bin':Buffer.from('reviewed fixture'),'000001.bin':Buffer.alloc(120003,97),'000002.bin':Buffer.alloc(0)};
const rows=Object.entries(objects).map(([blob,data],i)=>({path:'materials/fixture'+i+'.json',blob,bytes:data.length,sha256:sha(data),gitBlobSHA1:gitsha(data)}));
const metadata={schema:'iman-source-publication-bundle-v1',expectedHead:head,material:{language:'en',id:'fixture'},files:rows};
const options={root:"C:/Project/O'Brien",handoff:'C:/private/fixture.json',expectedHead:head,bundle:'C:/private/bundle',python:'C:/Python/python.exe',message:'Publish reviewed fixture'};
function mock({badBlob=false,failVerify=0,failRef=false,failTools=0}={}){
  const calls=[];let verifications=0,updates=0,toolChecks=0;
  return {calls,get verifications(){return verifications},get updates(){return updates},tools:{
    exec_command:async ({cmd})=>{
      calls.push(cmd);
      if(cmd.includes('import hashlib,pathlib,subprocess,sys')){toolChecks++;return {exit_code:toolChecks===failTools?1:0,output:''}}
      if(cmd.includes('--bundle-out'))return {exit_code:0,output:'{}'};
      if(cmd.includes('--verify-bundle')){verifications++;return {exit_code:verifications===failVerify?1:0,output:'{}'}}
      if(cmd.includes('import json,sys'))return {exit_code:0,output:JSON.stringify(metadata)};
      if(cmd.startsWith('git -C '))return {exit_code:0,output:base};
      if(cmd.includes('import base64,sys')){
        const match=cmd.match(/objects\/(\d{6}[.]bin)'\s+(\d+)$/);assert.ok(match,cmd);
        return {exit_code:0,output:objects[match[1]].subarray(Number(match[2]),Number(match[2])+120000).toString('base64')};
      }
      throw new Error('Unexpected fixture command');
    },
    mcp__codex_apps__github_create_blob:async ({content})=>({structuredContent:{sha:badBlob?'0'.repeat(40):gitsha(Buffer.from(content,'base64'))}}),
    mcp__codex_apps__github_create_tree:async args=>{assert.equal(args.base_tree_sha,base);assert.equal(args.tree_elements.length,3);return {structuredContent:{sha:tree}}},
    mcp__codex_apps__github_create_commit:async args=>{assert.equal(args.parent_sha,head);assert.equal(args.tree_sha,tree);return {structuredContent:{sha:commit}}},
    mcp__codex_apps__github_update_ref:async args=>{updates++;assert.equal(args.expected_sha,head);assert.equal(args.sha,commit);assert.equal(args.force,false);return failRef?{isError:true}:{structuredContent:{success:true}}}
  }};
}
async function main(){
  let m=mock();const result=await publishReviewedSourceWithConnector(options,m.tools);
  assert.equal(result.commit,commit);assert.equal(result.files,3);assert.equal(m.verifications,3);assert.equal(m.updates,1);
  assert.ok(m.calls.some(c=>c.includes("O''Brien")));
  m=mock({badBlob:true});await assert.rejects(()=>publishReviewedSourceWithConnector(options,m.tools),/blob differs/);assert.equal(m.updates,0);
  m=mock({failVerify:3});await assert.rejects(()=>publishReviewedSourceWithConnector(options,m.tools),/validation failed/);assert.equal(m.updates,0);
  m=mock({failTools:2});await assert.rejects(()=>publishReviewedSourceWithConnector(options,m.tools),/validation failed/);assert.equal(m.updates,0);
  m=mock({failRef:true});await assert.rejects(()=>publishReviewedSourceWithConnector(options,m.tools),/main advanced/);
  await assert.rejects(()=>publishReviewedSourceWithConnector({...options,expectedHead:'invalid'},mock().tools),/Git head/);
  console.log('Connector transaction preserves exact bytes and rejects stale or changed inputs.');
}
main().catch(e=>{console.error(e);process.exitCode=1});
