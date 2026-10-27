// Audit exported operations and their imported frontend consumers using TypeScript AST.
const fs = require('fs')
const path = require('path')
const ts = require('../../frontend/node_modules/typescript')
const root = path.resolve(__dirname, '../..')
function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap(e => e.isDirectory()
    ? files(path.join(dir, e.name)) : /\.tsx?$/.test(e.name) ? [path.join(dir, e.name)] : [])
}
const sources = files(path.join(root, 'frontend/src')).map(file => ({ file,
  ast: ts.createSourceFile(file, fs.readFileSync(file, 'utf8'), ts.ScriptTarget.Latest, true) }))
const operations = []
const typeContracts = []
for (const { file, ast } of sources.filter(s => /services[\\/](api|auth)\.ts$/.test(s.file))) {
  for (const node of ast.statements) {
    if (ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node)) {
      typeContracts.push({ name: node.name.text, file: path.relative(root, file).replaceAll('\\', '/'), definition: node.getText(ast) })
    }
    if (!ts.isFunctionDeclaration(node) || !node.name || !node.body ||
      !node.modifiers?.some(m => m.kind === ts.SyntaxKind.ExportKeyword)) continue
    const text = node.getText(ast)
    const endpoint = text.match(/\/(api\/[a-zA-Z0-9_/$}{.?=-]+|health)/)?.[0]
    if (!endpoint) continue
    let method = text.match(/method:\s*['"]([A-Z]+)['"]/)?.[1]
    if (!method) method = text.includes('postJson<') || text.includes('postJson(') ? 'POST' : 'GET'
    const consumers = []
    for (const candidate of sources.filter(s => s.file !== file)) {
      for (const declaration of candidate.ast.statements.filter(ts.isImportDeclaration)) {
        if (!/(?:services\/|^\.\/)(api|auth)$/.test(declaration.moduleSpecifier.text)) continue
        for (const specifier of declaration.importClause?.namedBindings?.elements || []) {
          if ((specifier.propertyName || specifier.name).text !== node.name.text || specifier.isTypeOnly) continue
          const calls = []
          function visit(n) {
            if (ts.isIdentifier(n) && n.text === specifier.name.text && !ts.isImportSpecifier(n.parent)) {
              calls.push(candidate.ast.getLineAndCharacterOfPosition(n.getStart()).line + 1)
            }
            ts.forEachChild(n, visit)
          }
          ts.forEachChild(candidate.ast, visit)
          if (calls.length) consumers.push({ file: path.relative(root, candidate.file).replaceAll('\\', '/'), lines: [...new Set(calls)] })
        }
      }
    }
    operations.push({ name: node.name.text, file: path.relative(root, file).replaceAll('\\', '/'),
      method, endpoint_expression: endpoint, signature: text.slice(0, node.body.getStart() - node.getStart()), implementation: text, consumers })
  }
}
const output = { counting: 'Exported API operation definitions containing a concrete route expression, including unused compatibility wrappers; helpers/local session functions excluded.',
  total: operations.length, operations, type_contracts: typeContracts }
fs.writeFileSync(path.join(root, 'docs/FRONTEND_API_INVENTORY.json'), JSON.stringify(output, null, 2))
console.log(JSON.stringify({ total: output.total, unused: operations.filter(o => !o.consumers.length).map(o => o.name) }))
