/* Single-transaction GitHub App bridge for the sole source publisher.
   This module uses only the caller-supplied tools interface; it never reads
   credentials or treats raw source uploads as approvals. */
async function publishReviewedSourceWithConnector(options, tools) {
  const repo = 'blaghtayt-alt/iman-companion';
  const { root, handoff, expectedHead, bundle, python, message } = options;
  if (!/^[a-f0-9]{40}$/.test(expectedHead || '')) throw new Error('Exact current Git head is required');
  const quote = value => {
    if (typeof value !== 'string' || !value || /[\x00-\x1f]/.test(value)) throw new Error('Invalid source publication argument');
    return "'" + value.replace(/'/g, "''") + "'";
  };
  for (const value of [root,handoff,bundle,python,message]) quote(value);
  const script = root.replace(/[\\/]$/, '') + '/books/source_publication_transaction.py';
  const run = async (cmd, max_output_tokens=10000) => {
    const r = await tools.exec_command({cmd,max_output_tokens});
    if (r.exit_code !== 0) throw new Error('Local source publication validation failed');
    return r.output.trim();
  };
  // The exact checked-out code is part of the reviewed transaction. Reject
  // added, removed, or locally edited Python modules, including import shadows.
  const checkCode = "import hashlib,pathlib,subprocess,sys; r=pathlib.Path(sys.argv[1]).resolve(); h=sys.argv[2]; raw=subprocess.check_output(['git','ls-tree','-rz','--full-tree',h,'--','books'],cwd=r); rows=[x.split(b'\\t',1) for x in raw.split(b'\\0') if x]; tracked={p.decode():m.split()[2].decode() for m,p in rows if p.endswith(b'.py')}; local={p.relative_to(r).as_posix():p for p in (r/'books').rglob('*.py')}; assert set(local)==set(tracked) and all(not p.is_symlink() and hashlib.sha1(b'blob '+str(p.stat().st_size).encode()+b'\\0'+p.read_bytes()).hexdigest()==tracked[n] for n,p in local.items())";
  const checkTools = () => run(`& ${quote(python)} -I -c ${quote(checkCode)} ${quote(root)} ${quote(expectedHead)}`);
  // Isolated mode ignores environment-injected Python paths, while explicitly
  // adding only the verified repository's book module directory.
  const launcher = "import runpy,sys;sys.path.insert(0,sys.argv[1]);sys.argv=sys.argv[2:];runpy.run_path(sys.argv[0],run_name='__main__')";
  const common = `& ${quote(python)} -I -c ${quote(launcher)} ${quote(root.replace(/[\\/]$/, '')+'/books')} ${quote(script)} --root ${quote(root)} --handoff ${quote(handoff)} --expected-head ${quote(expectedHead)}`;
  await checkTools();
  await run(`${common} --bundle-out ${quote(bundle)}`);
  const reader = "import json,sys;print(open(sys.argv[1],encoding='utf8').read())";
  const metadata = JSON.parse(await run(`& ${quote(python)} -c ${quote(reader)} ${quote(bundle.replace(/[\\/]$/, '')+'/manifest.json')}`,30000));
  if (metadata.schema !== 'iman-source-publication-bundle-v1' || metadata.expectedHead !== expectedHead || !Array.isArray(metadata.files) || !metadata.files.length) throw new Error('Invalid source publication bundle');
  await run(`${common} --verify-bundle ${quote(bundle)}`);
  const baseTree = await run(`git -C ${quote(root)} rev-parse ${quote(expectedHead+'^{tree}')}`);
  if (!/^[a-f0-9]{40}$/.test(baseTree)) throw new Error('Invalid source repository tree');
  const seen=new Set(), tree=[];
  for (const row of metadata.files) {
    if (typeof row.path !== 'string' || !row.path || seen.has(row.path) || !/^[0-9]{6}[.]bin$/.test(row.blob) || !Number.isSafeInteger(row.bytes) || row.bytes < 0 || !/^[a-f0-9]{64}$/.test(row.sha256) || !/^[a-f0-9]{40}$/.test(row.gitBlobSHA1)) throw new Error('Invalid bundled source file');
    seen.add(row.path);
    const file=bundle.replace(/[\\/]$/, '')+'/objects/'+row.blob, size=120000, chunks=[];
    const offsets=Array.from({length:Math.ceil(row.bytes/size)},(_,i)=>i*size);
    const readChunk="import base64,sys;f=open(sys.argv[1],'rb');f.seek(int(sys.argv[2]));print(base64.b64encode(f.read(120000)).decode())";
    for(let i=0;i<offsets.length;i+=8){
      const group=offsets.slice(i,i+8),results=await Promise.all(group.map(offset=>run(`& ${quote(python)} -c ${quote(readChunk)} ${quote(file)} ${offset}`,100000)));
      for(let j=0;j<group.length;j++){
        if(results[j].length!==4*Math.ceil(Math.min(size,row.bytes-group[j])/3))throw new Error('Bundled source read was incomplete');
        chunks.push(results[j]);
      }
    }
    const blob=await tools.mcp__codex_apps__github_create_blob({repository_full_name:repo,encoding:'base64',content:chunks.join('')});
    if(blob.isError || blob.structuredContent?.sha!==row.gitBlobSHA1)throw new Error('GitHub source blob differs from reviewed bytes');
    tree.push({path:row.path,mode:'100644',type:'blob',sha:row.gitBlobSHA1});
  }
  await run(`${common} --verify-bundle ${quote(bundle)}`);
  const created=await tools.mcp__codex_apps__github_create_tree({repository_full_name:repo,base_tree_sha:baseTree,tree_elements:tree});
  if(created.isError || !/^[a-f0-9]{40}$/.test(created.structuredContent?.sha||''))throw new Error('GitHub source tree was not created');
  const commit=await tools.mcp__codex_apps__github_create_commit({repository_full_name:repo,parent_sha:expectedHead,tree_sha:created.structuredContent.sha,message});
  if(commit.isError || !/^[a-f0-9]{40}$/.test(commit.structuredContent?.sha||''))throw new Error('GitHub source commit was not created');
  await run(`${common} --verify-bundle ${quote(bundle)}`);
  await checkTools();
  const updated=await tools.mcp__codex_apps__github_update_ref({repository_full_name:repo,branch_name:'main',expected_sha:expectedHead,sha:commit.structuredContent.sha,force:false});
  if(updated.isError || updated.structuredContent?.success!==true)throw new Error('GitHub main advanced or could not be updated');
  return {published:true,commit:commit.structuredContent.sha,material:metadata.material,files:tree.length};
}
if(typeof module!=='undefined')module.exports={publishReviewedSourceWithConnector};
