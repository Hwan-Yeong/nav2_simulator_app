// three.js preview of a robot profile (body extruded from the footprint, wheels, lidars with FOV fans).
import * as THREE from 'three';
import { OrbitControls } from '/static/vendor/three/OrbitControls.js';
import { robotPolygon } from './viewport.js';
import { cssVar } from './ui.js';

export class Robot3D {
  constructor(container) {
    this.el = container;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    this.renderer.setPixelRatio(Math.min(devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    container.append(this.renderer.domElement);
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(40, 1, 0.01, 100);
    this.camera.up.set(0, 0, 1);              // ROS convention: z up
    this.camera.position.set(-1.3, -1.6, 1.2);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.target.set(0, 0, 0.1);
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x445566, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-2, -3, 5);
    sun.castShadow = true;
    sun.shadow.mapSize.set(1024, 1024);
    Object.assign(sun.shadow.camera, { left: -2, right: 2, top: 2, bottom: -2 });
    this.scene.add(sun);
    this.ground = new THREE.Mesh(new THREE.PlaneGeometry(12, 12), new THREE.ShadowMaterial({ opacity: 0.18 }));
    this.ground.receiveShadow = true;
    this.scene.add(this.ground);
    this.group = new THREE.Group();
    this.scene.add(this.group);
    this.themeChanged();
    new ResizeObserver(() => this.resize()).observe(container);
    this.resize();
    const loop = () => { this.controls.update(); this.renderer.render(this.scene, this.camera); this.raf = requestAnimationFrame(loop); };
    loop();
  }

  themeChanged() {
    if (this.grid) this.scene.remove(this.grid);
    const line = new THREE.Color(cssVar('--line-strong') || '#c4ccd4');
    const faint = new THREE.Color(cssVar('--line') || '#dbe1e7');
    this.grid = new THREE.GridHelper(6, 60, line, faint);
    this.grid.rotation.x = Math.PI / 2;
    this.grid.position.z = 0.0005;
    this.scene.add(this.grid);
    if (this.profile) this.update(this.profile);
  }

  resize() {
    const r = this.el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    this.renderer.setSize(r.width, r.height, false);
    this.camera.aspect = r.width / r.height;
    this.camera.updateProjectionMatrix();
  }

  update(p) {
    this.profile = p;
    for (const c of [...this.group.children]) { this.group.remove(c); c.traverse((o) => { o.geometry && o.geometry.dispose(); }); }
    const poly = robotPolygon(p, 48);
    const circ = Math.max(...poly.map(([x, y]) => Math.hypot(x, y)), 0.1);
    const fanR = Math.max(0.15, circ * 0.8);
    if (this.fitFor !== p.name + circ.toFixed(3)) {   // frame the camera on a new robot
      this.fitFor = p.name + circ.toFixed(3);
      const d = circ * 5.5 + 0.4;
      this.camera.position.set(-d * 0.75, -d * 0.95, d * 0.75);
      this.controls.target.set(0, 0, Math.min(0.3, (p.body.height || 0.1) / 2));
    }
    const wr = p.wheels.radius || 0.05;
    const base = Math.max(0.01, wr * 0.35);
    const hgt = Math.max(0.02, p.body.height || 0.1);
    const shape = new THREE.Shape(poly.map(([x, y]) => new THREE.Vector2(x, y)));
    const body = new THREE.Mesh(
      new THREE.ExtrudeGeometry(shape, { depth: hgt, bevelEnabled: true, bevelThickness: Math.min(0.012, hgt * 0.15), bevelSize: 0.008, bevelSegments: 2 }),
      new THREE.MeshStandardMaterial({ color: new THREE.Color(p.body.color || '#3d4b55'), roughness: 0.55, metalness: 0.1 }));
    body.position.z = base;
    body.castShadow = true;
    this.group.add(body);
    // footprint padding outline on the floor
    const pad = p.footprint_padding || 0;
    if (pad > 0) {
      const R = Math.max(...poly.map(([x, y]) => Math.hypot(x, y)));
      const pts = poly.map(([x, y]) => { const r = Math.hypot(x, y) || 1; const k = (r + pad) / r; return new THREE.Vector3(x * k, y * k, 0.002); });
      pts.push(pts[0].clone());
      this.group.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color: new THREE.Color(cssVar('--accent')), dashSize: 0.02, gapSize: 0.015 })).computeLineDistances());
      void R;
    }
    // heading arrow on top
    const reach = Math.max(...poly.map(([x]) => x));
    const arrow = new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0, base + hgt + 0.02), Math.max(reach, 0.15) + 0.08,
      new THREE.Color(cssVar('--robot')), 0.06, 0.04);
    this.group.add(arrow);
    // wheels
    const wmat = new THREE.MeshStandardMaterial({ color: 0x22272b, roughness: 0.8 });
    const wheel = (x, y, steer = 0) => {
      const m = new THREE.Mesh(new THREE.CylinderGeometry(wr, wr, Math.max(0.02, wr * 0.6), 28), wmat);
      m.position.set(x, y, wr);
      m.rotation.z = steer;
      m.castShadow = true;
      this.group.add(m);
    };
    const tw = (p.wheels.track || 0.3) / 2;
    if (p.drive === 'diff') { wheel(0, tw); wheel(0, -tw); }
    else if (p.drive === 'omni') { const L = (p.wheels.wheelbase || 0.4) / 2; for (const sx of [L, -L]) { wheel(sx, tw); wheel(sx, -tw); } }
    else { const L = p.wheels.wheelbase || 0.5; wheel(0, tw); wheel(0, -tw); const st = (p.wheels.max_steer_deg || 0) * Math.PI / 360; wheel(L, tw, st); wheel(L, -tw, st); }
    // lidars
    for (const s of p.sensors || []) {
      const puck = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.04, 0.045, 24), new THREE.MeshStandardMaterial({ color: 0x14181c, roughness: 0.4 }));
      puck.rotation.x = Math.PI / 2;
      puck.position.set(s.x, s.y, s.z);
      puck.castShadow = true;
      this.group.add(puck);
      const fov = Math.min(360, s.fov_deg) * Math.PI / 180;
      const yaw = (s.yaw_deg || 0) * Math.PI / 180;
      const fan = new THREE.Mesh(new THREE.CircleGeometry(Math.min(s.range_max, fanR), 48, yaw - fov / 2, fov),
        new THREE.MeshBasicMaterial({ color: new THREE.Color(cssVar('--scan')), transparent: true, opacity: 0.12, side: THREE.DoubleSide, depthWrite: false }));
      fan.position.set(s.x, s.y, s.z);
      this.group.add(fan);
    }
  }

  dispose() { cancelAnimationFrame(this.raf); this.renderer.dispose(); }
}
