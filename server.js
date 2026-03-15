import express from "express";
import multer from "multer";
import fs from "node:fs/promises";
import path from "node:path";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const execFileAsync = promisify(execFile);

const app = express();
const port = process.env.PORT || 4678;
const upload = multer({ storage: multer.memoryStorage() });
const publicDir = path.join(__dirname, "public");
const tempDir = path.join(__dirname, "tmp", "pdfs");
const pythonPath = path.join(__dirname, "tools", "python311", "python.exe");
const enginePath = path.join(__dirname, "tools", "pdf_engine.py");
const templateTransformPath = path.join(__dirname, "tools", "template_transform.py");

await fs.mkdir(tempDir, { recursive: true });

app.use(express.json({ limit: "10mb" }));
app.use(
  express.static(publicDir, {
    setHeaders(res) {
      res.setHeader("Cache-Control", "no-store");
    }
  })
);

app.post("/api/analyze", upload.single("pdf"), async (req, res) => {
  try {
    if (!req.file) {
      return res.status(400).json({ error: "PDF dosyasi gerekli." });
    }

    const sourceId = `${Date.now()}-${sanitizeFilename(req.file.originalname)}`;
    const sourcePath = path.join(tempDir, sourceId);
    const manifestPath = `${sourcePath}.json`;
    const publicAnalysisPath = `${sourcePath}.public.json`;

    await fs.writeFile(sourcePath, req.file.buffer);

    await runPythonJson(enginePath, [
      "analyze",
      "--input",
      sourcePath,
      "--source",
      sourceId,
      "--file-name",
      req.file.originalname,
      "--manifest",
      manifestPath,
      "--public-output",
      publicAnalysisPath
    ]);

    const analysis = JSON.parse(await fs.readFile(publicAnalysisPath, "utf8"));
    res.json(analysis);
  } catch (error) {
    console.error(error);
    res.status(500).json({ error: error.message || "PDF incelenirken bir hata olustu." });
  }
});

app.post("/api/replace", async (req, res) => {
  try {
    const { source, replacements = [], templateTransforms = [] } = req.body;
    if (!source || (!Array.isArray(replacements) && !Array.isArray(templateTransforms))) {
      return res.status(400).json({ error: "Gecerli kaynak ve degisiklik listesi gerekli." });
    }
    if (!replacements.length && !templateTransforms.length) {
      return res.status(400).json({ error: "Kaydedilecek bir degisiklik bulunamadi." });
    }

    const sourcePath = path.join(tempDir, source);
    const manifestPath = `${sourcePath}.json`;
    const editsPath = `${sourcePath}.edits.json`;
    const replaceOutputPath = `${sourcePath}.updated.pdf`;
    const transformSpecPath = `${sourcePath}.template-transforms.json`;
    const transformOutputPath = `${sourcePath}.templated.pdf`;

    await fs.access(sourcePath);
    await fs.access(manifestPath);

    let workingInputPath = sourcePath;

    if (replacements.length) {
      await fs.writeFile(editsPath, JSON.stringify(replacements, null, 2), "utf8");

      await runPythonJson(enginePath, [
        "replace",
        "--input",
        sourcePath,
        "--manifest",
        manifestPath,
        "--edits",
        editsPath,
        "--output",
        replaceOutputPath
      ]);
      workingInputPath = replaceOutputPath;
    }

    if (templateTransforms.length) {
      await fs.writeFile(transformSpecPath, JSON.stringify(templateTransforms, null, 2), "utf8");
      await runPythonJson(templateTransformPath, [
        "--input",
        workingInputPath,
        "--transforms",
        transformSpecPath,
        "--output",
        transformOutputPath
      ]);
      workingInputPath = transformOutputPath;
    }

    const updatedBytes = await fs.readFile(workingInputPath);
    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Disposition", 'attachment; filename="duzenlenmis.pdf"');
    res.send(updatedBytes);
  } catch (error) {
    console.error(error);
    const statusCode = /sigmiyor|desteklenmeyen|duzenlenebilir degil|bos metin/i.test(error.message || "") ? 400 : 500;
    res.status(statusCode).json({ error: error.message || "PDF guncellenirken bir hata olustu." });
  }
});

app.listen(port, () => {
  console.log(`PDF editor app listening on http://localhost:${port}`);
});

async function runPythonJson(scriptPath, args) {
  try {
    const { stdout, stderr } = await execFileAsync(pythonPath, [scriptPath, ...args], {
      cwd: __dirname,
      maxBuffer: 100 * 1024 * 1024,
      encoding: "utf8"
    });

    if (stderr?.trim()) {
      console.error(stderr);
    }

    return parsePythonPayload(stdout);
  } catch (error) {
    const candidate = String(error.stdout || error.stderr || error.message || "").trim();
    if (!candidate) {
      throw new Error("Python engine calistirilamadi.");
    }

    try {
      const payload = JSON.parse(candidate);
      if (payload?.error) {
        throw new Error(payload.error);
      }
      return payload;
    } catch (parseError) {
      if (parseError instanceof SyntaxError) {
        throw new Error(candidate);
      }
      throw parseError;
    }
  }
}

function parsePythonPayload(raw) {
  const value = String(raw || "").trim();
  if (!value) {
    throw new Error("Python engine bos yanit dondu.");
  }

  const payload = JSON.parse(value);
  if (payload?.error) {
    throw new Error(payload.error);
  }

  return payload;
}

function sanitizeFilename(filename) {
  return filename.replace(/[^a-zA-Z0-9.-]/g, "_");
}
