// Подпись релиза своим ключом (ключ загрузки для Google Play).
// Если переменная DASYNC_UPLOAD_KEYSTORE не задана, сборка подписывается отладочным ключом
// (годится для прямой установки, но не для Google Play).
const { withAppBuildGradle } = require('expo/config-plugins');

module.exports = function withReleaseSigning(config) {
  return withAppBuildGradle(config, (cfg) => {
    let g = cfg.modResults.contents;
    if (g.includes('DASYNC_UPLOAD_KEYSTORE')) return cfg;

    const sc = 'signingConfigs {\n        debug {';
    if (!g.includes(sc)) throw new Error('with-release-signing: не нашёл signingConfigs в build.gradle');
    g = g.replace(
      sc,
      `signingConfigs {
        release {
            if (System.getenv("DASYNC_UPLOAD_KEYSTORE")) {
                storeFile file(System.getenv("DASYNC_UPLOAD_KEYSTORE"))
                storeType "pkcs12"
                storePassword System.getenv("DASYNC_UPLOAD_STORE_PASSWORD")
                keyAlias System.getenv("DASYNC_UPLOAD_KEY_ALIAS")
                keyPassword System.getenv("DASYNC_UPLOAD_STORE_PASSWORD")
            }
        }
        debug {`,
    );

    const bt = g.indexOf('buildTypes {');
    const rel = g.indexOf('release {', bt);
    const needle = 'signingConfig signingConfigs.debug';
    const at = g.indexOf(needle, rel);
    if (bt < 0 || rel < 0 || at < 0) throw new Error('with-release-signing: не нашёл release в buildTypes');
    g =
      g.slice(0, at) +
      'signingConfig(System.getenv("DASYNC_UPLOAD_KEYSTORE") ? signingConfigs.release : signingConfigs.debug)' +
      g.slice(at + needle.length);

    cfg.modResults.contents = g;
    return cfg;
  });
};
