#version 330
uniform sampler2D u_tex;
uniform vec3 u_cam;
uniform vec3 u_fog;
uniform vec2 u_fog_range;
uniform vec3 u_sun_dir;
uniform vec2 u_wind_dir;
uniform float u_time;
uniform int u_anim_mode;
uniform int u_cutout;
uniform float u_alpha;
uniform vec2 u_uv_offset;
in vec2 v_uv;
in float v_shade;
in vec3 v_world;
in float v_wave_height;
in float v_anim_alpha;
in float v_flex;
in vec3 v_water_normal;
in float v_water_crest;
out vec4 frag;

float hash21(vec2 p) {
    p = fract(p * vec2(123.34, 456.21));
    p += dot(p, p + 45.32);
    return fract(p.x * p.y);
}

float noise21(vec2 p) {
    vec2 i = floor(p);
    vec2 f = fract(p);
    f = f * f * (3.0 - 2.0 * f);
    float a = hash21(i);
    float b = hash21(i + vec2(1.0, 0.0));
    float c = hash21(i + vec2(0.0, 1.0));
    float d = hash21(i + vec2(1.0, 1.0));
    return mix(mix(a, b, f.x), mix(c, d, f.x), f.y);
}

void main() {
    vec4 tex = texture(u_tex, v_uv + u_uv_offset);
    if (u_cutout == 1 && tex.a < 0.5) discard;

    vec3 normal = normalize(cross(dFdx(v_world), dFdy(v_world)));
    if (!gl_FrontFacing) normal = -normal;
    vec3 sunDir = normalize(u_sun_dir);
    vec3 viewDir = normalize(u_cam - v_world);

    if (u_anim_mode == 2 && v_flex > 0.5 && abs(normal.y) > 0.55) {
        normal = normalize(v_water_normal);
        if (normal.y < 0.0) normal = -normal;

        float NoV = max(dot(normal, viewDir), 0.001);
        float NoL = max(dot(normal, sunDir), 0.0);
        float fresnel = 0.02 + 0.98 * pow(1.0 - NoV, 5.0);

        // Approximate sky reflection with a view-dependent horizon tint.
        vec3 skyReflection = mix(vec3(0.035, 0.115, 0.145),
                                 u_fog * vec3(1.12, 1.10, 1.06),
                                 clamp(0.42 + normal.y * 0.52, 0.0, 1.0));
        vec3 deepWater = vec3(0.004, 0.035, 0.052);
        vec3 bodyWater = vec3(0.012, 0.095, 0.115);
        float depthTint = clamp(0.42 + v_wave_height * 0.42, 0.0, 1.0);
        vec3 waterColor = mix(deepWater, bodyWater, depthTint);
        vec3 col = mix(waterColor, skyReflection, fresnel * 0.82);

        // Tight sun glints and broader highlights follow the actual wave normal.
        vec3 reflectedSun = reflect(-sunDir, normal);
        float sunGlint = pow(max(dot(reflectedSun, viewDir), 0.0), 110.0);
        float softGlint = pow(max(dot(reflectedSun, viewDir), 0.0), 28.0);
        col += vec3(1.0, 0.78, 0.52) * sunGlint * (0.55 + NoL * 0.65);
        col += vec3(0.36, 0.53, 0.55) * softGlint * 0.10;

        // Crest foam breaks into irregular patches instead of a continuous stripe.
        float n1 = noise21(v_world.xz * 1.8 + vec2(u_time * 0.12, -u_time * 0.08));
        float n2 = noise21(v_world.xz * 4.2 - vec2(u_time * 0.19, u_time * 0.06));
        float foamNoise = n1 * 0.62 + n2 * 0.38;
        float crest = smoothstep(0.34, 0.72, v_water_crest + (foamNoise - 0.5) * 0.38);
        crest *= smoothstep(0.18, 0.72, v_wave_height + 0.12);
        vec3 foamColor = mix(vec3(0.66, 0.79, 0.78), vec3(0.94, 0.94, 0.86),
                             max(dot(normal, sunDir), 0.0) * 0.65);
        col = mix(col, foamColor, crest * 0.78);

        float distanceToCamera = distance(v_world, u_cam);
        float fog = smoothstep(u_fog_range.x, u_fog_range.y, distanceToCamera);
        col = mix(col, u_fog, fog);
        frag = vec4(col, 0.90 * u_alpha);
        return;
    }

    float ndl = max(dot(normal, sunDir), 0.0);
    float skyFill = 0.43 + 0.16 * clamp(normal.y, 0.0, 1.0);
    float lighting = clamp(skyFill + ndl * 0.55, 0.38, 1.12);
    vec3 col = tex.rgb * v_shade * lighting;
    float groundBounce = exp(-max(v_world.y, 0.0) * 0.032);
    col += vec3(0.060, 0.038, 0.020) * groundBounce
           * (1.0 - max(normal.y, 0.0)) * tex.rgb;
    if (u_anim_mode == 1) {
        float backLight = max(dot(-normal, sunDir), 0.0);
        col += tex.rgb * vec3(0.10, 0.15, 0.055) * backLight;
    }
    float d = distance(v_world, u_cam);
    float heightFog = smoothstep(42.0, 115.0, d) * 0.16;
    float f = clamp(smoothstep(u_fog_range.x, u_fog_range.y, d) + heightFog, 0.0, 1.0);
    col = mix(col, u_fog, f);
    col += vec3((hash21(gl_FragCoord.xy + floor(u_time * 2.0)) - 0.5) / 255.0);
    frag = vec4(max(col, vec3(0.0)), tex.a * u_alpha * v_anim_alpha);
}
