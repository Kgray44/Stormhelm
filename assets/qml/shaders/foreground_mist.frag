#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float depth;
    vec4 rectA;
    vec4 rectB;
    vec4 rectC;
    vec4 rectD;
};

float hash(vec2 p) {
    return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453123);
}

float noise(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    float a = hash(i);
    float b = hash(i + vec2(1.0, 0.0));
    float c = hash(i + vec2(0.0, 1.0));
    float d = hash(i + vec2(1.0, 1.0));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

float fbm(vec2 p) {
    float value = 0.0;
    float amplitude = 0.5;
    for (int i = 0; i < 4; ++i) {
        value += noise(p) * amplitude;
        p = p * 2.06 + vec2(3.2, 4.7);
        amplitude *= 0.5;
    }
    return value;
}

float edgeBand(vec2 uv, vec4 rect) {
    if (rect.z <= 0.0 || rect.w <= 0.0) {
        return 0.0;
    }

    vec2 center = rect.xy + rect.zw * 0.5;
    vec2 delta = abs(uv - center) - rect.zw * 0.5;
    float signedDistance = length(max(delta, vec2(0.0))) + min(max(delta.x, delta.y), 0.0);

    float nearOuterEdge = 1.0 - smoothstep(0.025, 0.12, abs(signedDistance));
    float keepOutOfContent = 1.0 - smoothstep(-0.09, -0.02, signedDistance);
    return nearOuterEdge * keepOutOfContent;
}

void main() {
    vec2 uv = qt_TexCoord0;
    float t = time * 6.28318;
    float strength = clamp(depth, 0.0, 1.0);

    float band = max(max(edgeBand(uv, rectA), edgeBand(uv, rectB)), max(edgeBand(uv, rectC), edgeBand(uv, rectD)));
    float field = fbm(uv * vec2(1.65, 0.92) + vec2(t * 0.018, -t * 0.010));
    float detail = fbm(uv * vec2(3.20, 1.55) + vec2(-t * 0.012, t * 0.007));
    float mist = smoothstep(0.52, 0.82, field * 0.72 + detail * 0.20);

    float edgeFade = smoothstep(0.0, 0.04, uv.x) * smoothstep(1.0, 0.96, uv.x)
                   * smoothstep(0.0, 0.04, uv.y) * smoothstep(1.0, 0.96, uv.y);

    vec3 tint = mix(vec3(0.34, 0.40, 0.44), vec3(0.28, 0.35, 0.39), detail);
    float alpha = band * mist * edgeFade * mix(0.004, 0.012, strength);

    fragColor = vec4(tint * alpha, alpha) * qt_Opacity;
}
