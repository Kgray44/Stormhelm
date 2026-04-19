#version 440
layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float depth;
    float layerScale;
    float phaseOffset;
    float fullField;
    float centerBias;
    vec2 drift;
    vec2 focusPoint;
    vec2 spread;
    vec4 tintColor;
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
        p = p * 2.03 + vec2(4.3, 2.1);
        amplitude *= 0.5;
    }
    return value;
}

float particleField(vec2 uv, vec2 scaleVec, vec2 flow, float seed) {
    vec2 p = uv * scaleVec + flow;
    vec2 cell = floor(p);
    vec2 local = fract(p);
    float accum = 0.0;

    for (int j = -1; j <= 1; ++j) {
        for (int i = -1; i <= 1; ++i) {
            vec2 id = cell + vec2(float(i), float(j));
            float chance = hash(id + vec2(seed, seed * 1.73));
            if (chance < 0.42) {
                continue;
            }

            vec2 centerJitter = vec2(
                hash(id + vec2(3.2 + seed, 1.7)),
                hash(id + vec2(6.1, 4.8 + seed))
            );
            vec2 center = vec2(float(i), float(j)) + centerJitter;
            center += vec2(
                sin(seed + time * 6.28318 * 0.06 + chance * 6.28318),
                cos(seed * 1.2 + time * 6.28318 * 0.05 + centerJitter.x * 6.28318)
            ) * 0.16;

            vec2 delta = local - center;
            delta.y *= 0.72;
            float radius = mix(0.28, 0.54, hash(id + vec2(8.3, 2.6)));
            float dist = length(delta);
            float particle = 1.0 - smoothstep(radius * 0.36, radius, dist);
            accum += particle * mix(0.35, 0.82, chance);
        }
    }

    return accum;
}

void main() {
    vec2 uv = qt_TexCoord0;
    float t = time * 6.28318 + phaseOffset;
    float strength = clamp(depth, 0.0, 1.0);
    float scale = max(layerScale, 0.08);

    vec2 flowA = drift * (t * 0.42);
    vec2 flowB = vec2(-drift.y, drift.x) * (t * 0.31);
    vec2 flowC = drift * (t * 0.18);

    float particlesA = particleField(uv, vec2(scale * 7.0, scale * 3.9), flowA, 1.7 + phaseOffset);
    float particlesB = particleField(uv, vec2(scale * 11.0, scale * 5.8), flowB, 4.1 + phaseOffset);
    float particlesC = particleField(uv, vec2(scale * 15.0, scale * 8.2), flowC, 7.3 + phaseOffset);
    float wisps = fbm(uv * vec2(scale * 0.78, scale * 0.40) + flowA * 0.4);
    float pressure = fbm(uv * vec2(scale * 0.34, scale * 0.20) + flowB * 0.2);

    float density = particlesA * 0.52 + particlesB * 0.28 + particlesC * 0.12 + wisps * 0.06 + pressure * 0.02;
    float mist = smoothstep(0.22, 0.86, density);

    vec2 offset = (uv - focusPoint) / max(spread, vec2(0.001));
    float centered = exp(-dot(offset, offset));
    float broadField = exp(-pow(offset.y / 1.8, 2.0)) * exp(-pow(offset.x / 1.45, 2.0));
    float mask = mix(centered, broadField, fullField);
    mask = max(mask, centered * centerBias);
    mask = mix(mask, 1.0, fullField * 0.08);

    float edgeFade = smoothstep(0.0, 0.06, uv.x) * smoothstep(1.0, 0.94, uv.x)
                   * smoothstep(0.0, 0.05, uv.y) * smoothstep(1.0, 0.95, uv.y);

    vec3 tint = tintColor.rgb * mix(0.82, 1.00, pressure);
    float alpha = mist * mask * edgeFade * strength * 0.82 * tintColor.a;

    fragColor = vec4(tint * alpha, alpha) * qt_Opacity;
}
