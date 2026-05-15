import { CubismModelSettingJson } from "@cubism-framework/cubismmodelsettingjson";
import { CubismFramework, LogLevel, Option } from "@cubism-framework/live2dcubismframework";
import { CubismDefaultParameterId } from "@cubism-framework/cubismdefaultparameterid";
import { BreathParameterData, CubismBreath } from "@cubism-framework/effect/cubismbreath";
import { CubismEyeBlink } from "@cubism-framework/effect/cubismeyeblink";
import { CubismMatrix44 } from "@cubism-framework/math/cubismmatrix44";
import type { CubismIdHandle } from "@cubism-framework/id/cubismid";
import { CubismUserModel } from "@cubism-framework/model/cubismusermodel";
import type { ACubismMotion } from "@cubism-framework/motion/acubismmotion";
import type { CubismMotion } from "@cubism-framework/motion/cubismmotion";
import { CubismBlendMode } from "@cubism-framework/rendering/cubismrenderer";
import { CubismShaderManager_WebGL } from "@cubism-framework/rendering/cubismshader_webgl";
import { loadCubismCore } from "./cubismCoreLoader";

export type CubismRendererOptions = {
  canvas: HTMLCanvasElement;
  modelDirectoryUrl: string;
  modelFileName: string;
};

export type CubismRenderMode = "official" | "fallback" | "failed";

export type CubismRendererResizeSize = {
  width: number;
  height: number;
  pixelRatio: number;
};

export type CubismRendererDiagnostics = {
  renderMode: CubismRenderMode;
  idleMotionEnabled: boolean;
  eyeBlinkEnabled: boolean;
  breathEnabled: boolean;
  physicsEnabled: boolean;
  motionCount: number;
  expressionCount: number;
  textureCount: number;
  shaderReady: boolean;
  currentMotion: { group: string; index: number } | null;
  currentExpression: string | null;
  visiblePixels: boolean | null;
  lastMotionError?: string;
  lastExpressionError?: string;
  lastEffectError?: string;
  lastOfficialRenderError?: string;
  lastFallbackRenderError?: string;
};

export type CubismRendererHandle = {
  start(): void;
  resize(size?: CubismRendererResizeSize): void;
  dispose(): void;
  setExpression(name: string): void;
  startMotion(group: string, index?: number): void;
  getRenderMode(): CubismRenderMode;
  getDiagnostics(): CubismRendererDiagnostics;
  hasVisiblePixels(): boolean;
};

const shaderPath = "/live2d/CubismSdkForWeb-5-r.5/Framework/Shaders/WebGL/";
const firstFrameTimeoutMs = 5000;
const shaderReadyTimeoutMs = 5000;
const firstFrameNoVisiblePixelMessage = "Live2D first frame rendered, but visible pixel sampling did not hit an opaque area.";
const visiblePixelColorThreshold = 18;
const visiblePixelAlphaThreshold = 8;
const visiblePixelSampleIntervalMs = 2000;
const initialVisiblePixelSamples = 2;
const enableIdleMotion = true;
const enablePhysics = true;
const enableBasicMeshFallback = false;
const petModelVisibleScale = 0.82;
const petModelTargetCenterX = 0;
const petModelTargetCenterY = -0.06;

let frameworkStarted = false;

type BasicMeshProgram = {
  program: WebGLProgram;
  positionLocation: number;
  uvLocation: number;
  matrixLocation: WebGLUniformLocation;
  textureLocation: WebGLUniformLocation;
  opacityLocation: WebGLUniformLocation;
  positionBuffer: WebGLBuffer;
  uvBuffer: WebGLBuffer;
  indexBuffer: WebGLBuffer;
};

type DrawableBounds = {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
};

export async function createCubismRenderer(options: CubismRendererOptions): Promise<CubismRendererHandle> {
  await loadCubismCore();
  ensureCubismFrameworkStarted();

  const gl = options.canvas.getContext("webgl2", { alpha: true, premultipliedAlpha: true })
    || options.canvas.getContext("webgl", { alpha: true, premultipliedAlpha: true });
  if (!gl) {
    throw new Error("WebGL context is not available for Live2D rendering.");
  }

  const model = new SingleCubismModel(options.modelDirectoryUrl);
  const manifestBuffer = await fetchArrayBuffer(`${options.modelDirectoryUrl}${options.modelFileName}`, "模型清单");
  await runCubismStage("模型初始化", () => model.loadFromManifest(manifestBuffer, gl, options.canvas));

  let frameId: number | null = null;
  let disposed = false;
  let firstFrameSettled = false;
  let resolveFirstFrame: (() => void) | null = null;
  let rejectFirstFrame: ((error: Error) => void) | null = null;
  const firstFrame = new Promise<void>((resolve, reject) => {
    resolveFirstFrame = resolve;
    rejectFirstFrame = reject;
  });

  const settleFirstFrame = () => {
    if (firstFrameSettled) {
      return;
    }
    firstFrameSettled = true;
    resolveFirstFrame?.();
  };

  const failFirstFrame = (error: unknown) => {
    if (firstFrameSettled) {
      console.error("[Cubism] runtime render failed after mount.", error);
      return;
    }
    firstFrameSettled = true;
    rejectFirstFrame?.(error instanceof Error ? error : new Error("Cubism first frame render failed."));
  };

  const handle: CubismRendererHandle = {
    start() {
      if (disposed || frameId !== null) {
        return;
      }
      const tick = () => {
        if (disposed) {
          return;
        }
        if (document.visibilityState === "hidden" || options.canvas.width <= 0 || options.canvas.height <= 0) {
          frameId = window.requestAnimationFrame(tick);
          return;
        }
        try {
          if (model.render(options.canvas, gl)) {
            settleFirstFrame();
          }
        } catch (error) {
          failFirstFrame(error);
          handle.dispose();
          return;
        }
        frameId = window.requestAnimationFrame(tick);
      };
      frameId = window.requestAnimationFrame(tick);
    },
    resize(size) {
      resizeCanvas(options.canvas, size);
      model.resize(options.canvas);
    },
    dispose() {
      disposed = true;
      if (frameId !== null) {
        window.cancelAnimationFrame(frameId);
        frameId = null;
      }
      model.release();
    },
    getRenderMode() {
      return model.getRenderMode();
    },
    getDiagnostics() {
      return model.getDiagnostics();
    },
    hasVisiblePixels() {
      if (gl.isContextLost()) {
        model.setVisiblePixels(false);
        return false;
      }
      return model.getCachedVisiblePixels();
    },
    setExpression(name) {
      model.setExpression(name);
    },
    startMotion(group, index = 0) {
      model.startMotion(group, index);
    },
  };

  handle.resize();
  handle.start();
  try {
    await waitForFirstFrame(firstFrame);
  } catch (error) {
    handle.dispose();
    throw error;
  }
  return handle;
}

function ensureCubismFrameworkStarted() {
  if (frameworkStarted) {
    return;
  }

  const option = new Option();
  option.loggingLevel = LogLevel.LogLevel_Warning;
  option.logFunction = (message: string) => {
    console.info(`[Cubism] ${message}`);
  };
  CubismFramework.startUp(option);
  CubismFramework.initialize();
  frameworkStarted = true;
}

class SingleCubismModel extends CubismUserModel {
  public readonly startedAt = performance.now();
  private readonly modelDirectoryUrl: string;
  private textureIds: WebGLTexture[] = [];
  private ready = false;
  private motionGroup = "";
  private motionIndex = -1;
  private idleMotion: CubismMotion | null = null;
  private motionMap = new Map<string, CubismMotion>();
  private expressionMap = new Map<string, ACubismMotion>();
  private currentExpressionName: string | null = null;
  private lastFrameTime = performance.now();
  private currentMvpMatrix = new Float32Array(16);
  private cachedDrawableBounds: DrawableBounds | null = null;
  private basicMeshProgram: BasicMeshProgram | null = null;
  private renderMode: CubismRenderMode = "official";
  private shaderReady = false;
  private visiblePixels: boolean | null = null;
  private lastVisiblePixelSampleAt = 0;
  private visiblePixelSampleCount = 0;
  private visiblePixelConfirmed = false;
  private lastMotionError: string | undefined;
  private lastExpressionError: string | undefined;
  private lastEffectError: string | undefined;
  private lastOfficialRenderError: string | undefined;
  private lastFallbackRenderError: string | undefined;

  constructor(modelDirectoryUrl: string) {
    super();
    this.modelDirectoryUrl = modelDirectoryUrl;
  }

  async loadFromManifest(manifestBuffer: ArrayBuffer, gl: WebGLRenderingContext | WebGL2RenderingContext, canvas: HTMLCanvasElement) {
    const setting = await runCubismStage(
      "模型清单解析",
      () => new CubismModelSettingJson(manifestBuffer, manifestBuffer.byteLength),
    );
    const modelFileName = setting.getModelFileName();
    if (!modelFileName) {
      throw new Error("model3.json does not declare a Moc file.");
    }

    const mocBuffer = await fetchArrayBuffer(`${this.modelDirectoryUrl}${modelFileName}`, "Moc 模型");
    await runCubismStage("Moc 模型解析", () => this.loadModel(mocBuffer, false));
    if (!this.getModel()) {
      throw new Error("Moc parsing failed; Cubism did not create a drawable model.");
    }
    this.setInitialized(true);
    this.setUpdating(false);

    const layout = new Map<string, number>();
    if (setting.getLayoutMap(layout)) {
      this.getModelMatrix().setupFromLayout(layout);
    } else {
      this.getModelMatrix().setCenterPosition(0, 0);
    }

    this.initializeEyeBlink(setting);
    this.initializeBreath();

    const physicsFileName = setting.getPhysicsFileName();
    if (enablePhysics && physicsFileName) {
      const physicsBuffer = await fetchArrayBuffer(`${this.modelDirectoryUrl}${physicsFileName}`, "物理配置");
      await runCubismStage("物理配置加载", () => this.loadPhysics(physicsBuffer, physicsBuffer.byteLength));
    }
    await this.loadExpressions(setting);
    if (enableIdleMotion) {
      await this.loadMotions(setting);
      this.startIdleMotion();
    }

    if (canvas.width <= 0 || canvas.height <= 0) {
      resizeCanvas(canvas);
    }
    await runCubismStage("renderer creation", () => this.createRenderer(canvas.width, canvas.height));
    await runCubismStage("WebGL renderer startup", () => this.getRenderer().startUp(gl));
    await runCubismStage("Shader 加载启动", () => this.getRenderer().loadShaders(shaderPath));
    await runCubismStage("贴图绑定", () => this.loadTextures(setting, gl));
    await waitForShaderReady(gl);
    this.shaderReady = true;
    assertRendererReady(this.getRenderer());
    if (this.textureIds.length <= 0) {
      throw new Error("Model has no bound textures; Live2D cannot render.");
    }
    assertNoWebGLError(gl, "Live2D model resource initialization");
    this.ready = true;
  }

  resize(canvas: HTMLCanvasElement) {
    this.setRenderTargetSize(canvas.width, canvas.height);
  }

  render(canvas: HTMLCanvasElement, gl: WebGLRenderingContext | WebGL2RenderingContext): boolean {
    if (!this.ready || !this.getModel() || gl.isContextLost()) {
      return false;
    }
    this.renderMode = "official";
    this.lastOfficialRenderError = undefined;
    this.lastFallbackRenderError = undefined;

    const now = performance.now();
    const deltaTimeSeconds = Math.min(0.1, Math.max(0, (now - this.lastFrameTime) / 1000));
    this.lastFrameTime = now;

    gl.viewport(0, 0, canvas.width, canvas.height);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);

    try {
      assertRendererReady(this.getRenderer());
      runCubismStageSync("模型参数读取", () => this.getModel().loadParameters());
      if (enableIdleMotion && this.motionIndex >= 0) {
        this.updateIdleMotionSafely(deltaTimeSeconds);
      }
      runCubismStageSync("模型参数保存", () => this.getModel().saveParameters());
      if (this.currentExpressionName) {
        runCubismStageSync("表情更新", () => this._expressionManager.updateMotion(this.getModel(), deltaTimeSeconds));
      }
      this.updateIdleEffectsSafely(deltaTimeSeconds);
      if (enablePhysics) {
        this.updatePhysicsSafely(deltaTimeSeconds);
      }
      runCubismStageSync("模型网格更新", () => this.getModel().update());
      const projection = this.createProjectionMatrix(canvas);
      this.currentMvpMatrix = new Float32Array(projection.getArray());
      this.getRenderer().setMvpMatrix(projection);
      const frameBuffer = gl.getParameter(gl.FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
      const viewport = [0, 0, canvas.width, canvas.height];
      runCubismStageSync("官方模型绘制", () => {
        this.getRenderer().setRenderState(frameBuffer as WebGLFramebuffer, viewport);
        this.getRenderer().drawModel(shaderPath);
      });
      if (this.shouldSampleVisiblePixels(now) && !this.sampleVisiblePixels(gl, canvas)) {
        this.lastOfficialRenderError = "官方 Cubism 渲染完成但画布没有可见模型像素。";
        if (performance.now() - this.startedAt >= firstFrameTimeoutMs) {
          console.warn(firstFrameNoVisiblePixelMessage);
        }
        if (enableBasicMeshFallback) {
          this.drawDrawableOnly(frameBuffer, viewport);
          this.renderMode = "fallback";
        }
      }
    } catch (error) {
      this.lastOfficialRenderError = formatUnknownError(error);
      console.warn("[Cubism] official renderer failed.", error);
      if (!enableBasicMeshFallback) {
        this.renderMode = "failed";
        throw wrapCubismError("Live2D 官方渲染", error);
      }
      try {
        const frameBuffer = gl.getParameter(gl.FRAMEBUFFER_BINDING) as WebGLFramebuffer | null;
        const viewport = [0, 0, canvas.width, canvas.height];
        this.drawDrawableOnly(frameBuffer, viewport);
        this.renderMode = "fallback";
        assertNoWebGLError(gl, "Live2D 基础网格绘制");
        if (!canvasHasVisiblePixels(gl, canvas)) {
          throw new Error("基础网格渲染完成但仍未检测到真实模型像素。");
        }
      } catch (fallbackError) {
        this.renderMode = "failed";
        this.lastFallbackRenderError = formatUnknownError(fallbackError);
        throw wrapCubismError("首帧绘制", fallbackError);
      }
    }
    return true;
  }

  getRenderMode(): CubismRenderMode {
    return this.renderMode;
  }

  override release() {
    for (const textureId of this.textureIds) {
      this.getRenderer()?.gl?.deleteTexture(textureId);
    }
    const gl = this.getRenderer()?.gl;
    if (gl && this.basicMeshProgram) {
      gl.deleteBuffer(this.basicMeshProgram.positionBuffer);
      gl.deleteBuffer(this.basicMeshProgram.uvBuffer);
      gl.deleteBuffer(this.basicMeshProgram.indexBuffer);
      gl.deleteProgram(this.basicMeshProgram.program);
      this.basicMeshProgram = null;
    }
    this.textureIds = [];
    super.release();
  }

  private async loadTextures(setting: CubismModelSettingJson, gl: WebGLRenderingContext | WebGL2RenderingContext) {
    const usePremultiply = true;
    for (let textureIndex = 0; textureIndex < setting.getTextureCount(); textureIndex += 1) {
      const textureFileName = setting.getTextureFileName(textureIndex);
      if (!textureFileName) {
        continue;
      }

      const texture = await createTextureFromImage(gl, `${this.modelDirectoryUrl}${textureFileName}`, usePremultiply);
      this.textureIds.push(texture);
      this.getRenderer().bindTexture(textureIndex, texture);
      this.getRenderer().setIsPremultipliedAlpha(usePremultiply);
    }
  }

  private async loadFirstMotion(setting: CubismModelSettingJson) {
    if (setting.getMotionGroupCount() <= 0) {
      return;
    }

    const group = setting.getMotionGroupName(0);
    if (setting.getMotionCount(group) <= 0) {
      return;
    }

    const motionFileName = setting.getMotionFileName(group, 0);
    if (!motionFileName) {
      return;
    }

    const motionBuffer = await fetchArrayBuffer(`${this.modelDirectoryUrl}${motionFileName}`, "idle 动作");
    const motion = await runCubismStage("idle 动作加载", () =>
      this.loadMotion(motionBuffer, motionBuffer.byteLength, `${group}_0`, undefined, undefined, setting, group, 0, false),
    );
    if (!motion) {
      return;
    }

    this.idleMotion = motion;
    this.motionGroup = group;
    this.motionIndex = 0;
    this.startLoadedMotion();
  }

  private async loadExpressions(setting: CubismModelSettingJson) {
    this.expressionMap.clear();
    this.currentExpressionName = null;
    this.lastExpressionError = undefined;
    const uniqueNames = new Set<string>();
    for (let expressionIndex = 0; expressionIndex < setting.getExpressionCount(); expressionIndex += 1) {
      const expressionFileName = setting.getExpressionFileName(expressionIndex);
      if (!expressionFileName) {
        continue;
      }

      const fileKey = createExpressionKey(expressionFileName);
      if (this.expressionMap.has(fileKey)) {
        continue;
      }

      try {
        const expressionBuffer = await fetchArrayBuffer(`${this.modelDirectoryUrl}${expressionFileName}`, `表情 ${fileKey}`);
        const expression = await runCubismStage("表情加载", () =>
          this.loadExpression(expressionBuffer, expressionBuffer.byteLength, fileKey),
        );
        if (!expression) {
          continue;
        }

        this.expressionMap.set(fileKey, expression);
        const displayName = setting.getExpressionName(expressionIndex);
        if (displayName && !uniqueNames.has(displayName)) {
          this.expressionMap.set(displayName, expression);
          uniqueNames.add(displayName);
        }
      } catch (error) {
        this.lastExpressionError = describeCubismError(error);
        console.warn(`[Cubism] 表情加载失败：${fileKey}`, error);
      }
    }
  }

  private async loadMotions(setting: CubismModelSettingJson) {
    this.motionMap.clear();
    this.motionGroup = "";
    this.motionIndex = -1;
    this.idleMotion = null;
    this.lastMotionError = undefined;

    for (let groupIndex = 0; groupIndex < setting.getMotionGroupCount(); groupIndex += 1) {
      const group = setting.getMotionGroupName(groupIndex);
      for (let motionIndex = 0; motionIndex < setting.getMotionCount(group); motionIndex += 1) {
        const motionFileName = setting.getMotionFileName(group, motionIndex);
        const key = createMotionKey(group, motionIndex);
        if (!motionFileName || this.motionMap.has(key)) {
          continue;
        }

        try {
          const motionBuffer = await fetchArrayBuffer(`${this.modelDirectoryUrl}${motionFileName}`, `动作 ${key}`);
          const motion = await runCubismStage("idle 动作加载", () =>
            this.loadMotion(motionBuffer, motionBuffer.byteLength, key, undefined, undefined, setting, group, motionIndex, false),
          );
          if (!motion) {
            continue;
          }
          motion.setEffectIds(this.getEyeBlinkParameterIds(setting), []);
          motion.setLoop(true);
          motion.setLoopFadeIn(false);
          this.motionMap.set(key, motion);
        } catch (error) {
          this.lastMotionError = describeCubismError(error);
          console.warn(`[Cubism] 动作加载失败：${key}`, error);
        }
      }
    }
  }

  private startIdleMotion() {
    const firstMotion = this.motionMap.entries().next();
    if (firstMotion.done) {
      return;
    }
    const { group, index } = parseMotionKey(firstMotion.value[0]);
    this.startMotion(group, index);
  }

  private startLoadedMotion() {
    if (!this.idleMotion) {
      return;
    }
    this._motionManager.startMotionPriority(this.idleMotion, false, 1);
  }

  private initializeEyeBlink(setting: CubismModelSettingJson) {
    const eyeBlink = CubismEyeBlink.create(setting);
    if (eyeBlink.getParameterIds().length <= 0) {
      return;
    }

    eyeBlink.setBlinkingInterval(3.2);
    eyeBlink.setBlinkingSetting(0.08, 0.06, 0.12);
    this._eyeBlink = eyeBlink;
  }

  private initializeBreath() {
    const idManager = CubismFramework.getIdManager();
    const breath = CubismBreath.create();
    breath.setParameters([
      new BreathParameterData(idManager.getId(CubismDefaultParameterId.ParamAngleX), 0.0, 8.0, 6.0, 0.35),
      new BreathParameterData(idManager.getId(CubismDefaultParameterId.ParamAngleY), 0.0, 6.0, 6.0, 0.25),
      new BreathParameterData(idManager.getId(CubismDefaultParameterId.ParamAngleZ), 0.0, 4.0, 6.0, 0.25),
      new BreathParameterData(idManager.getId(CubismDefaultParameterId.ParamBodyAngleX), 0.0, 5.0, 6.0, 0.35),
      new BreathParameterData(idManager.getId(CubismDefaultParameterId.ParamBreath), 0.5, 0.5, 3.5, 0.8),
    ]);
    this._breath = breath;
  }

  private getEyeBlinkParameterIds(setting: CubismModelSettingJson): CubismIdHandle[] {
    const parameterIds: CubismIdHandle[] = [];
    for (let index = 0; index < setting.getEyeBlinkParameterCount(); index += 1) {
      const parameterId = setting.getEyeBlinkParameterId(index);
      if (parameterId) {
        parameterIds.push(parameterId);
      }
    }
    return parameterIds;
  }

  private updateIdleMotionSafely(deltaTimeSeconds: number) {
    try {
      if (this._motionManager.isFinished()) {
        this.startLoadedMotion();
      } else {
        this._motionManager.updateMotion(this.getModel(), deltaTimeSeconds);
      }
      this.lastMotionError = undefined;
    } catch (error) {
      this.lastMotionError = `idle 动作更新失败，已关闭动作播放：${describeCubismError(error)}`;
      console.warn(`[Cubism] ${this.lastMotionError}`, error);
      this.motionIndex = -1;
      this.motionGroup = "";
      this.idleMotion = null;
      try {
        this._motionManager.stopAllMotions();
      } catch (stopError) {
        console.warn("[Cubism] 停止异常动作队列失败。", stopError);
      }
    }
  }

  private updateIdleEffectsSafely(deltaTimeSeconds: number) {
    try {
      this._eyeBlink?.updateParameters(this.getModel(), deltaTimeSeconds);
      this._breath?.updateParameters(this.getModel(), deltaTimeSeconds);
      this.lastEffectError = undefined;
    } catch (error) {
      this.lastEffectError = `Live2D 眨眼/呼吸更新失败，已保留模型渲染：${describeCubismError(error)}`;
      console.warn(`[Cubism] ${this.lastEffectError}`, error);
    }
  }

  private updatePhysicsSafely(deltaTimeSeconds: number) {
    try {
      this._physics?.evaluate(this.getModel(), deltaTimeSeconds);
    } catch (error) {
      this.lastEffectError = `Live2D 物理摆动更新失败，已保留模型渲染：${describeCubismError(error)}`;
      console.warn(`[Cubism] ${this.lastEffectError}`, error);
    }
  }

  setExpression(name: string) {
    const key = name.trim();
    if (!key) {
      return;
    }

    const expression = this.expressionMap.get(key);
    if (!expression) {
      this.lastExpressionError = `未找到表情：${key}`;
      console.info(`[Cubism] ${this.lastExpressionError}`);
      return;
    }

    this._expressionManager.startMotion(expression, false);
    this.currentExpressionName = key;
    this.lastExpressionError = undefined;
  }

  startMotion(group: string, index = 0) {
    const key = createMotionKey(group, index);
    const motion = this.motionMap.get(key);
    if (!motion) {
      this.lastMotionError = `未找到动作：${key}`;
      console.info(`[Cubism] ${this.lastMotionError}`);
      return;
    }

    this.idleMotion = motion;
    this.motionGroup = group;
    this.motionIndex = index;
    this.lastMotionError = undefined;
    this.startLoadedMotion();
  }

  getDiagnostics(): CubismRendererDiagnostics {
    return {
      renderMode: this.renderMode,
      idleMotionEnabled: enableIdleMotion,
      eyeBlinkEnabled: Boolean(this._eyeBlink),
      breathEnabled: Boolean(this._breath),
      physicsEnabled: enablePhysics,
      motionCount: this.motionMap.size,
      expressionCount: this.expressionMap.size,
      textureCount: this.textureIds.length,
      shaderReady: this.shaderReady,
      currentMotion: this.motionIndex >= 0 ? { group: this.motionGroup, index: this.motionIndex } : null,
      currentExpression: this.currentExpressionName,
      visiblePixels: this.visiblePixels,
      lastMotionError: this.lastMotionError,
      lastExpressionError: this.lastExpressionError,
      lastEffectError: this.lastEffectError,
      lastOfficialRenderError: this.lastOfficialRenderError,
      lastFallbackRenderError: this.lastFallbackRenderError,
    };
  }

  setVisiblePixels(visiblePixels: boolean) {
    this.visiblePixels = visiblePixels;
  }

  getCachedVisiblePixels(): boolean {
    return this.visiblePixels !== false;
  }

  private shouldSampleVisiblePixels(now: number): boolean {
    if (this.visiblePixelConfirmed) {
      return false;
    }

    if (this.visiblePixelSampleCount < initialVisiblePixelSamples) {
      return true;
    }

    return now - this.lastVisiblePixelSampleAt >= visiblePixelSampleIntervalMs;
  }

  private sampleVisiblePixels(gl: WebGLRenderingContext | WebGL2RenderingContext, canvas: HTMLCanvasElement): boolean {
    this.lastVisiblePixelSampleAt = performance.now();
    this.visiblePixelSampleCount += 1;
    const visible = canvasHasVisiblePixels(gl, canvas);
    this.setVisiblePixels(visible);
    if (visible) {
      this.visiblePixelConfirmed = true;
    }
    return visible;
  }

  private createProjectionMatrix(canvas: HTMLCanvasElement) {
    const projection = new CubismMatrix44();
    if (canvas.width < canvas.height) {
      projection.scale(1, canvas.width / canvas.height);
    } else {
      projection.scale(canvas.height / canvas.width, 1);
    }

    projection.multiplyByMatrix(this.createCenteredModelMatrix());
    return projection;
  }

  private createCenteredModelMatrix() {
    const modelMatrix = this.getModelMatrix().clone();
    const bounds = this.measureDrawableBounds();
    if (!bounds) {
      return modelMatrix;
    }

    modelMatrix.scaleRelative(petModelVisibleScale, petModelVisibleScale);

    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    const currentCenterX = modelMatrix.transformX(centerX);
    const currentCenterY = modelMatrix.transformY(centerY);

    modelMatrix.translateX(modelMatrix.getTranslateX() - currentCenterX + petModelTargetCenterX);
    modelMatrix.translateY(modelMatrix.getTranslateY() - currentCenterY + petModelTargetCenterY);
    return modelMatrix;
  }

  private measureDrawableBounds(): DrawableBounds | null {
    if (this.cachedDrawableBounds) {
      return this.cachedDrawableBounds;
    }

    const model = this.getModel();
    const drawableCount = model.getDrawableCount();
    let minX = Number.POSITIVE_INFINITY;
    let maxX = Number.NEGATIVE_INFINITY;
    let minY = Number.POSITIVE_INFINITY;
    let maxY = Number.NEGATIVE_INFINITY;

    for (let drawableIndex = 0; drawableIndex < drawableCount; drawableIndex += 1) {
      if (!model.getDrawableDynamicFlagIsVisible(drawableIndex) || model.getDrawableOpacity(drawableIndex) <= 0.001) {
        continue;
      }

      const vertices = model.getDrawableVertexPositions(drawableIndex);
      if (!vertices || vertices.length < 2) {
        continue;
      }

      for (let vertexIndex = 0; vertexIndex < vertices.length; vertexIndex += 2) {
        const x = vertices[vertexIndex];
        const y = vertices[vertexIndex + 1];
        if (!Number.isFinite(x) || !Number.isFinite(y)) {
          continue;
        }
        minX = Math.min(minX, x);
        maxX = Math.max(maxX, x);
        minY = Math.min(minY, y);
        maxY = Math.max(maxY, y);
      }
    }

    if (![minX, maxX, minY, maxY].every(Number.isFinite) || minX >= maxX || minY >= maxY) {
      return null;
    }

    this.cachedDrawableBounds = { minX, maxX, minY, maxY };
    return this.cachedDrawableBounds;
  }

  private drawDrawableOnly(frameBuffer: WebGLFramebuffer | null, viewport: number[]) {
    const model = this.getModel();
    const renderer = this.getRenderer();
    const gl = renderer.gl;
    const program = this.getBasicMeshProgram(gl);
    const textures = renderer.getBindedTextures();
    const drawableCount = model.getDrawableCount();
    const renderOrders = model.getRenderOrders();
    const drawableIndices = Array.from({ length: drawableCount }, (_, index) => index).sort(
      (left, right) => (renderOrders[left] ?? left) - (renderOrders[right] ?? right),
    );

    gl.bindFramebuffer(gl.FRAMEBUFFER, frameBuffer);
    gl.viewport(viewport[0], viewport[1], viewport[2], viewport[3]);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.useProgram(program.program);
    gl.uniformMatrix4fv(program.matrixLocation, false, this.createFallbackMeshMatrix(viewport));
    gl.uniform1i(program.textureLocation, 0);
    gl.activeTexture(gl.TEXTURE0);
    gl.enable(gl.BLEND);
    gl.disable(gl.DEPTH_TEST);

    for (const drawableIndex of drawableIndices) {
      runCubismStageSync("基础网格绘制", () => {
        const texture = textures.get(model.getDrawableTextureIndex(drawableIndex));
        if (!texture) {
          return;
        }

        const vertices = model.getDrawableVertexPositions(drawableIndex);
        const uvs = model.getDrawableVertexUvs(drawableIndex);
        const indices = model.getDrawableVertexIndices(drawableIndex);
        if (!vertices || !uvs || !indices || vertices.length === 0 || uvs.length === 0 || indices.length === 0) {
          return;
        }

        // fallback 渲染器的目标是兜底显示真实模型，不参与官方高级裁剪/遮罩。
        // Cubism 模型坐标与 WebGL 正反面在不同导出工具中可能不一致，启用 culling 会导致整模被剔除。
        gl.disable(gl.CULL_FACE);

        switch (model.getDrawableBlendMode(drawableIndex)) {
          case CubismBlendMode.CubismBlendMode_Additive:
            gl.blendFunc(gl.ONE, gl.ONE);
            break;
          case CubismBlendMode.CubismBlendMode_Multiplicative:
            gl.blendFunc(gl.DST_COLOR, gl.ONE_MINUS_SRC_ALPHA);
            break;
          default:
            gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
            break;
        }

        gl.bindTexture(gl.TEXTURE_2D, texture);
        gl.uniform1f(program.opacityLocation, model.getDrawableOpacity(drawableIndex));

        gl.bindBuffer(gl.ARRAY_BUFFER, program.positionBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, vertices, gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(program.positionLocation);
        gl.vertexAttribPointer(program.positionLocation, 2, gl.FLOAT, false, 0, 0);

        gl.bindBuffer(gl.ARRAY_BUFFER, program.uvBuffer);
        gl.bufferData(gl.ARRAY_BUFFER, uvs, gl.DYNAMIC_DRAW);
        gl.enableVertexAttribArray(program.uvLocation);
        gl.vertexAttribPointer(program.uvLocation, 2, gl.FLOAT, false, 0, 0);

        gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, program.indexBuffer);
        gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, indices, gl.DYNAMIC_DRAW);
        gl.drawElements(gl.TRIANGLES, indices.length, gl.UNSIGNED_SHORT, 0);
      });
    }

    gl.disableVertexAttribArray(program.positionLocation);
    gl.disableVertexAttribArray(program.uvLocation);
    gl.bindBuffer(gl.ARRAY_BUFFER, null);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, null);
    gl.bindTexture(gl.TEXTURE_2D, null);
    gl.useProgram(null);
  }

  private createFallbackMeshMatrix(viewport: number[]): Float32Array {
    const bounds = this.measureDrawableBounds();
    const viewportWidth = Math.max(1, viewport[2]);
    const viewportHeight = Math.max(1, viewport[3]);
    if (!bounds) {
      return this.currentMvpMatrix;
    }

    const modelWidth = Math.max(0.001, bounds.maxX - bounds.minX);
    const modelHeight = Math.max(0.001, bounds.maxY - bounds.minY);
    const targetPixelWidth = viewportWidth * 0.86;
    const targetPixelHeight = viewportHeight * 0.78;
    const pixelsPerModelUnit = Math.min(targetPixelWidth / modelWidth, targetPixelHeight / modelHeight);
    const scaleX = (2 * pixelsPerModelUnit) / viewportWidth;
    const scaleY = (2 * pixelsPerModelUnit) / viewportHeight;
    const centerX = (bounds.minX + bounds.maxX) / 2;
    const centerY = (bounds.minY + bounds.maxY) / 2;
    const targetCenterX = 0;
    const targetCenterY = 0.02;

    return new Float32Array([
      scaleX, 0, 0, 0,
      0, scaleY, 0, 0,
      0, 0, 1, 0,
      targetCenterX - centerX * scaleX,
      targetCenterY - centerY * scaleY,
      0,
      1,
    ]);
  }

  private getBasicMeshProgram(gl: WebGLRenderingContext | WebGL2RenderingContext): BasicMeshProgram {
    if (this.basicMeshProgram) {
      return this.basicMeshProgram;
    }

    const vertexShader = compileShader(
      gl,
      gl.VERTEX_SHADER,
      `
        attribute vec2 a_position;
        attribute vec2 a_uv;
        uniform mat4 u_matrix;
        varying vec2 v_uv;
        void main() {
          gl_Position = u_matrix * vec4(a_position, 0.0, 1.0);
          v_uv = a_uv;
        }
      `,
    );
    const fragmentShader = compileShader(
      gl,
      gl.FRAGMENT_SHADER,
      `
        precision mediump float;
        varying vec2 v_uv;
        uniform sampler2D u_texture;
        uniform float u_opacity;
        void main() {
          vec4 color = texture2D(u_texture, v_uv);
          gl_FragColor = vec4(color.rgb, color.a * u_opacity);
        }
      `,
    );
    const program = linkProgram(gl, vertexShader, fragmentShader);
    gl.deleteShader(vertexShader);
    gl.deleteShader(fragmentShader);

    const matrixLocation = gl.getUniformLocation(program, "u_matrix");
    const textureLocation = gl.getUniformLocation(program, "u_texture");
    const opacityLocation = gl.getUniformLocation(program, "u_opacity");
    const positionBuffer = gl.createBuffer();
    const uvBuffer = gl.createBuffer();
    const indexBuffer = gl.createBuffer();

    if (!matrixLocation || !textureLocation || !opacityLocation || !positionBuffer || !uvBuffer || !indexBuffer) {
      throw new Error("Basic WebGL mesh renderer initialization failed.");
    }

    this.basicMeshProgram = {
      program,
      positionLocation: gl.getAttribLocation(program, "a_position"),
      uvLocation: gl.getAttribLocation(program, "a_uv"),
      matrixLocation,
      textureLocation,
      opacityLocation,
      positionBuffer,
      uvBuffer,
      indexBuffer,
    };
    return this.basicMeshProgram;
  }
}

function createMotionKey(group: string, index: number): string {
  return `${group}\u0000${index}`;
}

function parseMotionKey(key: string): { group: string; index: number } {
  const separatorIndex = key.lastIndexOf("\u0000");
  if (separatorIndex < 0) {
    return { group: key, index: 0 };
  }
  return {
    group: key.slice(0, separatorIndex),
    index: Number(key.slice(separatorIndex + 1)) || 0,
  };
}

function removeFileExtension(fileName: string): string {
  const lastSlashIndex = fileName.lastIndexOf("/");
  const baseName = lastSlashIndex >= 0 ? fileName.slice(lastSlashIndex + 1) : fileName;
  const extensionIndex = baseName.lastIndexOf(".");
  return extensionIndex > 0 ? baseName.slice(0, extensionIndex) : baseName;
}

function createExpressionKey(fileName: string): string {
  return removeFileExtension(fileName);
}

function describeCubismError(error: unknown): string {
  return formatUnknownError(error);
}

function formatUnknownError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function fetchArrayBuffer(url: string, label: string): Promise<ArrayBuffer> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${label} load failed: ${response.status} ${url}`);
  }
  return response.arrayBuffer();
}

async function runCubismStage<T>(stage: string, action: () => T | Promise<T>): Promise<T> {
  try {
    return await action();
  } catch (error) {
    throw wrapCubismError(stage, error);
  }
}

function runCubismStageSync<T>(stage: string, action: () => T): T {
  try {
    return action();
  } catch (error) {
    throw wrapCubismError(stage, error);
  }
}

function wrapCubismError(stage: string, error: unknown): Error {
  if (error instanceof Error) {
    if (error.message.startsWith(`Live2D ${stage} failed`) || /^Live2D .+ failed:/.test(error.message)) {
      return error;
    }
    return new Error(`Live2D ${stage} failed: ${error.message}`);
  }
  return new Error(`Live2D ${stage} failed: unknown Cubism error.`);
}

function createTextureFromImage(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  url: string,
  usePremultiply: boolean,
): Promise<WebGLTexture> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      const texture = gl.createTexture();
      if (!texture) {
        reject(new Error(`Texture object creation failed: ${url}`));
        return;
      }

      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, usePremultiply ? 1 : 0);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
      if (isPowerOfTwo(image.naturalWidth) && isPowerOfTwo(image.naturalHeight)) {
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR_MIPMAP_LINEAR);
        gl.generateMipmap(gl.TEXTURE_2D);
      } else {
        gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      }
      assertNoWebGLError(gl, `Texture upload: ${url}`);
      gl.bindTexture(gl.TEXTURE_2D, null);
      resolve(texture);
    };
    image.onerror = () => reject(new Error(`Texture load failed: ${url}`));
    image.src = url;
  });
}

function compileShader(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  type: number,
  source: string,
): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) {
    throw new Error("Basic WebGL shader creation failed.");
  }

  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const message = gl.getShaderInfoLog(shader) || "Unknown shader compile error.";
    gl.deleteShader(shader);
    throw new Error(`Basic WebGL shader compile failed: ${message}`);
  }
  return shader;
}

function linkProgram(
  gl: WebGLRenderingContext | WebGL2RenderingContext,
  vertexShader: WebGLShader,
  fragmentShader: WebGLShader,
): WebGLProgram {
  const program = gl.createProgram();
  if (!program) {
    throw new Error("Basic WebGL program creation failed.");
  }

  gl.attachShader(program, vertexShader);
  gl.attachShader(program, fragmentShader);
  gl.linkProgram(program);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const message = gl.getProgramInfoLog(program) || "Unknown program link error.";
    gl.deleteProgram(program);
    throw new Error(`Basic WebGL program link failed: ${message}`);
  }
  return program;
}

function waitForFirstFrame(firstFrame: Promise<void>): Promise<void> {
  let timeoutId: number | null = null;
  const timeout = new Promise<never>((_, reject) => {
    timeoutId = window.setTimeout(() => {
      reject(new Error("Live2D Cubism WebGL first frame render timed out; shader, texture, or draw may not have completed."));
    }, firstFrameTimeoutMs);
  });

  return Promise.race([firstFrame, timeout]).finally(() => {
    if (timeoutId !== null) {
      window.clearTimeout(timeoutId);
    }
  });
}

function waitForShaderReady(gl: WebGLRenderingContext | WebGL2RenderingContext): Promise<void> {
  const startedAt = performance.now();

  return new Promise((resolve, reject) => {
    const poll = () => {
      if (CubismShaderManager_WebGL.getInstance().getShader(gl)._isShaderLoaded) {
        resolve();
        return;
      }

      if (performance.now() - startedAt >= shaderReadyTimeoutMs) {
        reject(new Error("Live2D shader load timed out; check that Cubism SDK shader static assets exist and return 200."));
        return;
      }

      window.setTimeout(poll, 16);
    };

    poll();
  });
}

function assertRendererReady(renderer: unknown) {
  const internalRenderer = renderer as {
    gl?: WebGLRenderingContext | WebGL2RenderingContext | null;
    _model?: unknown;
  };

  if (!renderer || !internalRenderer.gl || !internalRenderer._model) {
    throw new Error("Live2D renderer has not completed WebGL or model binding.");
  }
}

function canvasHasVisiblePixels(gl: WebGLRenderingContext | WebGL2RenderingContext, canvas: HTMLCanvasElement): boolean {
  try {
    const width = Math.max(1, canvas.width);
    const height = Math.max(1, canvas.height);
    const sample = new Uint8Array(4);
    const samplePoints = [
      [0.5, 0.5],
      [0.5, 0.38],
      [0.5, 0.62],
      [0.38, 0.5],
      [0.62, 0.5],
      [0.34, 0.34],
      [0.66, 0.34],
      [0.34, 0.66],
      [0.66, 0.66],
      [0.25, 0.5],
      [0.75, 0.5],
      [0.5, 0.25],
      [0.5, 0.75],
      [0.2, 0.7],
      [0.8, 0.7],
    ];

    for (const [ratioX, ratioY] of samplePoints) {
      const x = Math.min(width - 1, Math.max(0, Math.floor(width * ratioX)));
      const y = Math.min(height - 1, Math.max(0, Math.floor(height * ratioY)));
      gl.readPixels(x, y, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, sample);
      if (isVisibleModelPixel(sample)) {
        return true;
      }
    }

    assertNoWebGLError(gl, "Live2D pixel check");

    return false;
  } catch (error) {
    console.info("[Cubism] Live2D pixel sampling diagnostics failed; keeping render status degraded.", error);
    return false;
  }
}

function isVisibleModelPixel(sample: Uint8Array): boolean {
  if (sample[3] <= visiblePixelAlphaThreshold) {
    return false;
  }

  // Electron 的透明窗口在部分 WebGL 实现中会把清屏后的黑色背景读成 alpha 非 0。
  // 因此不能只用 alpha 判断可见性，必须确认采样点含有真实贴图颜色。
  return sample[0] + sample[1] + sample[2] >= visiblePixelColorThreshold;
}

function assertNoWebGLError(gl: WebGLRenderingContext | WebGL2RenderingContext, label: string) {
  const error = gl.getError();
  if (error !== gl.NO_ERROR) {
    throw new Error(`${label} WebGL error: 0x${error.toString(16)}`);
  }
}

function isPowerOfTwo(value: number): boolean {
  return value > 0 && (value & (value - 1)) === 0;
}

function resizeCanvas(canvas: HTMLCanvasElement, size?: CubismRendererResizeSize) {
  const bounds = canvas.getBoundingClientRect();
  const pixelRatio = size?.pixelRatio || window.devicePixelRatio || 1;
  const width = size?.width || Math.max(1, Math.round(bounds.width * pixelRatio));
  const height = size?.height || Math.max(1, Math.round(bounds.height * pixelRatio));

  if (canvas.width !== width) {
    canvas.width = width;
  }
  if (canvas.height !== height) {
    canvas.height = height;
  }
}
