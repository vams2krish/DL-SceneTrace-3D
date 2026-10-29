// Dependency-free WebGL isotropic Gaussian preview. CPU evaluator is authoritative.
const subtract=(a,b)=>a.map((v,i)=>v-b[i]);
const dot=(a,b)=>a.reduce((s,v,i)=>s+v*b[i],0);
const normalize=a=>{const l=Math.hypot(...a)||1;return a.map(v=>v/l);};
const cross=(a,b)=>[a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]];

export class GaussianViewer {
  constructor(canvas,onError){
    this.canvas=canvas; this.onError=onError; this.yaw=.5;this.pitch=.42;this.distance=7;this.center=[0,.8,0];this.mode=0;
    const gl=canvas.getContext('webgl',{alpha:false,antialias:true,preserveDrawingBuffer:true});
    if(!gl)throw new Error('WebGL is unavailable. Source images and validation remain accessible.');
    this.gl=gl;
    const compile=(type,source)=>{const shader=gl.createShader(type);gl.shaderSource(shader,source);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(shader));return shader;};
    const program=gl.createProgram();
    gl.attachShader(program,compile(gl.VERTEX_SHADER,`precision highp float;
      attribute vec3 position; attribute vec3 color; attribute float scale; attribute float opacity;
      uniform vec3 eye; uniform vec3 right; uniform vec3 up; uniform vec3 forward;
      uniform vec2 resolution; uniform float focal; uniform float mode; uniform float pixelRatio;
      varying vec3 vColor; varying float vOpacity;
      void main(){vec3 p=position-eye;float z=dot(p,forward);vec2 q=vec2(dot(p,right),dot(p,up));
      gl_Position=vec4(q.x*focal/resolution.x*2.0,q.y*focal/resolution.y*2.0,z-0.1,z);
      gl_PointSize=mode>0.5?2.4*pixelRatio:clamp(6.0*focal*scale/max(z,0.1),1.0,160.0);
      if(z<0.1){gl_Position=vec4(2.0,2.0,2.0,1.0);gl_PointSize=0.0;}
      vColor=color;vOpacity=opacity;}`));
    gl.attachShader(program,compile(gl.FRAGMENT_SHADER,`precision highp float;
      varying vec3 vColor;varying float vOpacity;uniform float mode;
      void main(){vec2 p=(gl_PointCoord-0.5)*6.0;float r=dot(p,p);if(r>9.0)discard;
      float a=mode>0.5?1.0:min(0.99,vOpacity*exp(-0.5*r));gl_FragColor=vec4(vColor,a);}`));
    gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
    this.program=program;this.buffer=gl.createBuffer();this.uniforms={};
    for(const name of ['eye','right','up','forward','resolution','focal','mode','pixelRatio'])this.uniforms[name]=gl.getUniformLocation(program,name);
    this.attributes={};for(const name of ['position','color','scale','opacity'])this.attributes[name]=gl.getAttribLocation(program,name);
    canvas.addEventListener('pointerdown',e=>{this.drag=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
    canvas.addEventListener('pointermove',e=>{if(!this.drag)return;this.yaw-=(e.clientX-this.drag[0])*.008;this.pitch=Math.max(-1.2,Math.min(1.35,this.pitch+(e.clientY-this.drag[1])*.006));this.drag=[e.clientX,e.clientY];this.draw();});
    canvas.addEventListener('pointerup',()=>this.drag=null);canvas.addEventListener('pointercancel',()=>this.drag=null);
    canvas.addEventListener('wheel',e=>{e.preventDefault();this.distance=Math.max(this.minDistance,Math.min(this.maxDistance,this.distance*Math.exp(e.deltaY*.001)));this.draw();},{passive:false});
    canvas.addEventListener('keydown',e=>{if(!['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','+','=','-'].includes(e.key))return;e.preventDefault();if(e.key==='ArrowLeft')this.yaw+=.12;if(e.key==='ArrowRight')this.yaw-=.12;if(e.key==='ArrowUp')this.pitch=Math.min(1.35,this.pitch+.1);if(e.key==='ArrowDown')this.pitch=Math.max(-1.2,this.pitch-.1);if(e.key==='+'||e.key==='=')this.distance=Math.max(this.minDistance,this.distance*.9);if(e.key==='-')this.distance=Math.min(this.maxDistance,this.distance*1.1);this.draw();});
    canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();this.onError('Graphics context lost. Reload to restore the 3D viewport.');});
    this.observer=new ResizeObserver(()=>this.draw());this.observer.observe(canvas);
  }
  setScene(scene){this.scene=scene;const p=scene.positions;const lo=[Infinity,Infinity,Infinity],hi=[-Infinity,-Infinity,-Infinity];for(const point of p)for(let i=0;i<3;i++){lo[i]=Math.min(lo[i],point[i]);hi[i]=Math.max(hi[i],point[i]);}this.center=lo.map((v,i)=>(v+hi[i])/2);this.homeDistance=Math.max(.2,Math.hypot(...subtract(hi,lo))*1.3);this.minDistance=this.homeDistance*.1;this.maxDistance=this.homeDistance*4;this.reset();}
  reset(){this.yaw=.52;this.pitch=.36;this.distance=this.homeDistance||7;this.draw();}
  camera(camera){if(!camera)return;let eye=camera.eye;if(!eye&&camera.R&&camera.t){eye=[0,1,2].map(i=>-camera.R.reduce((s,row,j)=>s+row[i]*camera.t[j],0));}if(!eye)return;const delta=subtract(eye,this.center);this.distance=Math.hypot(...delta);this.yaw=Math.atan2(delta[0],delta[2]);this.pitch=Math.asin(delta[1]/this.distance);this.draw();}
  setMode(mode){this.mode=mode;this.draw();}
  draw(){
    if(!this.scene||!this.canvas.clientWidth||!this.canvas.clientHeight)return;
    const gl=this.gl,dpr=Math.min(window.devicePixelRatio||1,2),width=Math.round(this.canvas.clientWidth*dpr),height=Math.round(this.canvas.clientHeight*dpr);
    if(this.canvas.width!==width||this.canvas.height!==height){this.canvas.width=width;this.canvas.height=height;}
    const eye=[this.center[0]+Math.sin(this.yaw)*Math.cos(this.pitch)*this.distance,this.center[1]+Math.sin(this.pitch)*this.distance,this.center[2]+Math.cos(this.yaw)*Math.cos(this.pitch)*this.distance];
    const forward=normalize(subtract(this.center,eye)),right=normalize(cross(forward,[0,1,0])),up=cross(right,forward);
    const scene=this.scene;const indices=scene.positions.map((p,i)=>[i,dot(subtract(p,eye),forward)]).sort((a,b)=>b[1]-a[1]);
    const data=new Float32Array(indices.length*8);indices.forEach(([i],j)=>data.set([...scene.positions[i],...scene.colors[i],scene.scales[i],scene.opacity[i]],j*8));
    gl.viewport(0,0,width,height);gl.clearColor(.035,.055,.078,1);gl.clear(gl.COLOR_BUFFER_BIT);gl.useProgram(this.program);gl.bindBuffer(gl.ARRAY_BUFFER,this.buffer);gl.bufferData(gl.ARRAY_BUFFER,data,gl.DYNAMIC_DRAW);
    const layout=[['position',3,0],['color',3,12],['scale',1,24],['opacity',1,28]];for(const [name,size,offset] of layout){gl.enableVertexAttribArray(this.attributes[name]);gl.vertexAttribPointer(this.attributes[name],size,gl.FLOAT,false,32,offset);}
    gl.uniform3fv(this.uniforms.eye,eye);gl.uniform3fv(this.uniforms.right,right);gl.uniform3fv(this.uniforms.up,up);gl.uniform3fv(this.uniforms.forward,forward);gl.uniform2f(this.uniforms.resolution,width,height);gl.uniform1f(this.uniforms.focal,height*1.05);gl.uniform1f(this.uniforms.mode,this.mode);gl.uniform1f(this.uniforms.pixelRatio,dpr);
    gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);gl.disable(gl.DEPTH_TEST);gl.drawArrays(gl.POINTS,0,indices.length);
  }
}
