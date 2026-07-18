/**
 * HTQWeb AdminJS Panel — unified admin for PostgreSQL + MongoDB.
 *
 * This service provides a single UI to manage:
 *   - PostgreSQL tables: users, employees, departments, positions (via Sequelize adapter)
 *   - MongoDB collections: hr_documents (via Mongoose adapter)
 *
 * Authentication: platform admin credentials via user-service, with env
 * fallback for break-glass local access.
 */

import AdminJS from 'adminjs';
import AdminJSExpress from '@adminjs/express';
import * as AdminJSSequelize from '@adminjs/sequelize';
import * as AdminJSMongoose from '@adminjs/mongoose';
import express from 'express';
import session from 'express-session';
import { Sequelize, DataTypes } from 'sequelize';
import mongoose from 'mongoose';

// ── Environment ─────────────────────────────────────────────────────────────
const DATABASE_URL = process.env.DATABASE_URL || 'postgres://htqweb:change-me@localhost:5432/htqweb';
const MONGO_URI = process.env.MONGO_URI || 'mongodb://htqweb:change-me-mongo@localhost:27017/htqweb_docs?authSource=admin';
const ADMIN_EMAIL = process.env.ADMIN_EMAIL || 'admin@htq.local';
const ADMIN_PASSWORD = process.env.ADMIN_PASSWORD || 'admin';
const JWT_SECRET = process.env.JWT_SECRET || 'change-me';
const USER_SERVICE_URL = process.env.USER_SERVICE_URL || 'http://user-service:8005';
const USER_SERVICE_AUTH_URLS = [
  USER_SERVICE_URL,
  'http://127.0.0.1:8005',
].map((url) => url.replace(/\/+$/, ''))
  .filter((url, index, urls) => urls.indexOf(url) === index);
const PORT = parseInt(process.env.PORT || '3300', 10);
const ADMIN_ROOT_PATH = normalizeRootPath(
  process.env.ADMIN_ROOT_PATH || process.env.ADMINJS_ROOT_PATH || '/mongo-admin',
);

function normalizeRootPath(value) {
  const raw = String(value || '/mongo-admin').trim();
  const withLeadingSlash = raw.startsWith('/') ? raw : `/${raw}`;
  return withLeadingSlash.replace(/\/+$/, '') || '/mongo-admin';
}

function decodeJwtPayload(token) {
  const [, payload] = String(token || '').split('.');
  if (!payload) return null;
  try {
    const normalized = payload.replace(/-/g, '+').replace(/_/g, '/');
    const padded = normalized.padEnd(Math.ceil(normalized.length / 4) * 4, '=');
    return JSON.parse(Buffer.from(padded, 'base64').toString('utf8'));
  } catch (_error) {
    return null;
  }
}

async function authenticatePlatformAdmin(email, password) {
  const login = String(email || '').trim();
  if (!login || !password) return null;

  for (const baseUrl of USER_SERVICE_AUTH_URLS) {
    try {
      const response = await fetch(`${baseUrl}/api/users/v1/token/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: login, password }),
      });
      if (!response.ok) continue;

      const body = await response.json();
      const payload = decodeJwtPayload(body.access);
      if (!payload?.is_admin && !payload?.is_staff && !payload?.is_superuser) {
        return null;
      }

      return {
        email: payload.email || login,
        title: payload.username || payload.email || login,
        userId: payload.user_id,
      };
    } catch (error) {
      console.warn(`AdminJS platform auth failed via ${baseUrl}:`, error.message);
    }
  }
  return null;
}

// ── Register adapters ───────────────────────────────────────────────────────
AdminJS.registerAdapter(AdminJSSequelize);
AdminJS.registerAdapter(AdminJSMongoose);

// ── PostgreSQL via Sequelize ────────────────────────────────────────────────
const sequelize = new Sequelize(DATABASE_URL, {
  logging: console.log,
  dialectOptions: {
    // PgBouncer in transaction mode needs this
    options: '-c search_path=public,hr',
  },
});

// Define Sequelize models matching the existing PostgreSQL tables.
// These are READ models — AdminJS uses them for browsing/editing, but the
// source of truth remains the FastAPI services and their Alembic migrations.

const User = sequelize.define('User', {
  id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
  username: { type: DataTypes.STRING(150), unique: true },
  email: { type: DataTypes.STRING(254), unique: true },
  first_name: DataTypes.STRING(150),
  last_name: DataTypes.STRING(150),
  patronymic: DataTypes.STRING(100),
  display_name: DataTypes.STRING(100),
  status: DataTypes.STRING(20),
  is_staff: DataTypes.BOOLEAN,
  is_superuser: DataTypes.BOOLEAN,
  must_change_password: DataTypes.BOOLEAN,
  date_joined: DataTypes.DATE,
  last_login: DataTypes.DATE,
  created_at: DataTypes.DATE,
  updated_at: DataTypes.DATE,
}, {
  tableName: 'users',
  schema: 'public',
  timestamps: false,
});

const Department = sequelize.define('Department', {
  id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
  name: { type: DataTypes.STRING(255), unique: true },
  path: DataTypes.STRING(500),
  description: DataTypes.TEXT,
  manager_id: DataTypes.INTEGER,
  is_active: DataTypes.BOOLEAN,
  unit_type: DataTypes.STRING(20),
  created_at: DataTypes.DATE,
  updated_at: DataTypes.DATE,
}, {
  tableName: 'hr_departments',
  timestamps: false,
});

const Position = sequelize.define('Position', {
  id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
  title: { type: DataTypes.STRING(255), unique: true },
  department_id: DataTypes.INTEGER,
  grade: DataTypes.INTEGER,
  description: DataTypes.TEXT,
  is_active: DataTypes.BOOLEAN,
  weight: DataTypes.INTEGER,
  level: DataTypes.INTEGER,
  created_at: DataTypes.DATE,
  updated_at: DataTypes.DATE,
}, {
  tableName: 'hr_positions',
  timestamps: false,
});

const Employee = sequelize.define('Employee', {
  id: { type: DataTypes.INTEGER, primaryKey: true, autoIncrement: true },
  user_id: DataTypes.INTEGER,
  first_name: DataTypes.STRING(100),
  last_name: DataTypes.STRING(100),
  middle_name: DataTypes.STRING(100),
  email: { type: DataTypes.STRING(255), unique: true },
  phone: DataTypes.STRING(20),
  department_id: DataTypes.INTEGER,
  position_id: DataTypes.INTEGER,
  hire_date: DataTypes.DATEONLY,
  termination_date: DataTypes.DATEONLY,
  status: DataTypes.STRING(20),
  is_deleted: DataTypes.BOOLEAN,
  created_at: DataTypes.DATE,
  updated_at: DataTypes.DATE,
}, {
  tableName: 'hr_employees',
  timestamps: false,
});

// ── MongoDB via Mongoose ────────────────────────────────────────────────────
const HRDocumentSchema = new mongoose.Schema({
  sql_employee_id: { type: Number, required: true, index: true },
  title: { type: String, required: true },
  doc_type: {
    type: String,
    enum: ['contract', 'order', 'certificate', 'policy', 'memo',
           'performance_review', 'disciplinary', 'training', 'other'],
    required: true,
  },
  content: { type: String, default: '' },
  file_url: String,
  file_size_bytes: Number,
  mime_type: { type: String, default: 'application/octet-stream' },
  tags: [String],
  metadata: { type: mongoose.Schema.Types.Mixed, default: {} },
  created_by_user_id: Number,
  created_at: { type: Date, default: Date.now },
  updated_at: { type: Date, default: Date.now },
}, {
  collection: 'hr_documents',
  timestamps: false,
});

const HRDocument = mongoose.model('HRDocument', HRDocumentSchema);

// ── AdminJS config ──────────────────────────────────────────────────────────
const adminJs = new AdminJS({
  rootPath: ADMIN_ROOT_PATH,
  loginPath: `${ADMIN_ROOT_PATH}/login`,
  logoutPath: `${ADMIN_ROOT_PATH}/logout`,
  branding: {
    companyName: 'HTQWeb Admin',
    logo: false,
    softwareBrothers: false,
  },
  resources: [
    // PostgreSQL resources
    {
      resource: User,
      options: {
        navigation: { name: 'PostgreSQL — Auth', icon: 'User' },
        listProperties: ['id', 'username', 'email', 'status', 'is_staff', 'is_superuser', 'date_joined'],
        editProperties: ['username', 'email', 'first_name', 'last_name', 'status', 'is_staff', 'is_superuser', 'must_change_password'],
        properties: {
          id: { isVisible: { list: true, filter: true, show: true, edit: false } },
        },
      },
    },
    {
      resource: Department,
      options: {
        navigation: { name: 'PostgreSQL — HR', icon: 'Home' },
        listProperties: ['id', 'name', 'path', 'is_active', 'unit_type'],
      },
    },
    {
      resource: Position,
      options: {
        navigation: { name: 'PostgreSQL — HR', icon: 'Briefcase' },
        listProperties: ['id', 'title', 'department_id', 'grade', 'weight', 'level', 'is_active'],
      },
    },
    {
      resource: Employee,
      options: {
        navigation: { name: 'PostgreSQL — HR', icon: 'Users' },
        listProperties: ['id', 'first_name', 'last_name', 'email', 'department_id', 'position_id', 'status'],
      },
    },
    // MongoDB resources
    {
      resource: HRDocument,
      options: {
        navigation: { name: 'MongoDB — HR Documents', icon: 'Document' },
        listProperties: ['_id', 'sql_employee_id', 'title', 'doc_type', 'created_at'],
        editProperties: ['sql_employee_id', 'title', 'doc_type', 'content', 'file_url', 'file_size_bytes', 'tags'],
        properties: {
          _id: { isVisible: { list: true, filter: true, show: true, edit: false } },
          sql_employee_id: {
            description: 'ID of employee in PostgreSQL hr_employees table',
          },
        },
      },
    },
  ],
});

// ── Express server ──────────────────────────────────────────────────────────
const app = express();

// Health endpoint for Docker healthcheck. Register before AdminJS so auth
// middleware cannot redirect it to the login page.
const healthHandler = (_req, res) => {
  res.json({ status: 'ok', service: 'adminjs-panel' });
};

app.get(`${ADMIN_ROOT_PATH}/api/health`, healthHandler);
app.get('/admin/api/health', healthHandler);

// Simple cookie-based auth
const adminRouter = AdminJSExpress.buildAuthenticatedRouter(adminJs, {
  authenticate: async (email, password) => {
    const platformAdmin = await authenticatePlatformAdmin(email, password);
    if (platformAdmin) return platformAdmin;

    if (email === ADMIN_EMAIL && password === ADMIN_PASSWORD) {
      return { email: ADMIN_EMAIL, title: 'Admin' };
    }
    return null;
  },
  cookiePassword: JWT_SECRET,
}, null, {
  resave: false,
  saveUninitialized: false,
  secret: JWT_SECRET,
});

app.use(adminJs.options.rootPath, adminRouter);

// ── Start ───────────────────────────────────────────────────────────────────
async function start() {
  try {
    // Connect PostgreSQL
    await sequelize.authenticate();
    console.log('✅ PostgreSQL connected');

    // Connect MongoDB
    await mongoose.connect(MONGO_URI);
    console.log('✅ MongoDB connected');

    app.listen(PORT, '0.0.0.0', () => {
      console.log(`🚀 AdminJS panel running at http://0.0.0.0:${PORT}${ADMIN_ROOT_PATH}`);
    });
  } catch (error) {
    console.error('❌ Failed to start AdminJS:', error);
    process.exit(1);
  }
}

start();
