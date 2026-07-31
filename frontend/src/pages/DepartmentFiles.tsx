import React, { useState, useCallback, useRef } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  createDepartmentFileFolder,
  fetchMyFolders,
  fetchDepartmentFileFolders,
  fetchFolderFiles,
  uploadFile,
  deleteFile,
  downloadFileUrl,
} from '@/api/fileManager';
import type { DepartmentFolder, DepartmentFile, DepartmentFileFolder } from '@/types/fileManager';
import { BackToProfile } from '@/components/BackToProfile';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Badge } from '@/components/ui/badge';
import { useToast } from '@/hooks/use-toast';
import {
  FolderOpen,
  Upload,
  Download,
  Trash2,
  FileText,
  FileImage,
  FileSpreadsheet,
  FileArchive,
  File as FileIcon,
  Loader2,
  Cloud,
  HardDrive,
  Search,
  X,
  FilePlus,
  FolderLock,
  ArrowLeft,
  FolderPlus,
} from 'lucide-react';

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

function formatBytes(bytes: number): string {
  if (bytes === 0) return '0 Б';
  const k = 1024;
  const sizes = ['Б', 'КБ', 'МБ', 'ГБ'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function getFileIcon(name: string) {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext))
    return <FileImage className="h-8 w-8 text-pink-400" />;
  if (['xls', 'xlsx', 'csv'].includes(ext))
    return <FileSpreadsheet className="h-8 w-8 text-green-400" />;
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext))
    return <FileArchive className="h-8 w-8 text-amber-400" />;
  if (['pdf'].includes(ext))
    return <FileText className="h-8 w-8 text-red-400" />;
  if (['doc', 'docx', 'txt', 'rtf'].includes(ext))
    return <FileText className="h-8 w-8 text-blue-400" />;
  return <FileIcon className="h-8 w-8 text-slate-400" />;
}

/** Split a filename into base + extension so the extension stays visible
 *  when the base is truncated (e.g. "очень длинное имя… .pdf"). */
function splitFileName(name: string): { base: string; ext: string } {
  const dot = name.lastIndexOf('.');
  if (dot <= 0 || dot === name.length - 1) return { base: name, ext: '' };
  return { base: name.slice(0, dot), ext: name.slice(dot) };
}

function getFileColor(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() || '';
  if (['jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp'].includes(ext))
    return 'from-pink-500/10 to-pink-500/5';
  if (['xls', 'xlsx', 'csv'].includes(ext))
    return 'from-green-500/10 to-green-500/5';
  if (['zip', 'rar', '7z', 'tar', 'gz'].includes(ext))
    return 'from-amber-500/10 to-amber-500/5';
  if (['pdf'].includes(ext))
    return 'from-red-500/10 to-red-500/5';
  if (['doc', 'docx', 'txt', 'rtf'].includes(ext))
    return 'from-blue-500/10 to-blue-500/5';
  return 'from-slate-500/10 to-slate-500/5';
}

function formatFileCount(count: number): string {
  const suffix =
    count === 1
      ? 'файл'
      : count % 10 >= 2 && count % 10 <= 4 && (count % 100 < 10 || count % 100 >= 20)
      ? 'файла'
      : 'файлов';
  return `${count} ${suffix}`;
}

/* ------------------------------------------------------------------ */
/*  Main Component                                                     */
/* ------------------------------------------------------------------ */

const DepartmentFiles: React.FC = () => {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [selectedFolder, setSelectedFolder] = useState<DepartmentFolder | null>(null);
  const [selectedFileFolder, setSelectedFileFolder] = useState<DepartmentFileFolder | null>(null);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [createFolderDialogOpen, setCreateFolderDialogOpen] = useState(false);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [fileToDelete, setFileToDelete] = useState<DepartmentFile | null>(null);
  const [uploadDescription, setUploadDescription] = useState('');
  const [newFolderName, setNewFolderName] = useState('');
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [isDragging, setIsDragging] = useState(false);

  /* ---------- Queries ---------- */

  const { data: folders = [], isLoading: foldersLoading } = useQuery({
    queryKey: ['department-folders'],
    queryFn: fetchMyFolders,
  });

  const { data: fileFolders = [], isLoading: fileFoldersLoading } = useQuery({
    queryKey: ['department-file-folders', selectedFolder?.id],
    queryFn: () => fetchDepartmentFileFolders(selectedFolder!.id),
    enabled: !!selectedFolder,
  });

  const { data: files = [], isLoading: filesLoading } = useQuery({
    queryKey: ['department-files', selectedFolder?.id, selectedFileFolder?.id ?? 'root'],
    queryFn: () =>
      fetchFolderFiles(selectedFolder!.id, {
        fileFolderId: selectedFileFolder?.id ?? null,
        rootOnly: !selectedFileFolder,
      }),
    enabled: !!selectedFolder,
  });

  /* ---------- Mutations ---------- */

  const uploadMutation = useMutation({
    mutationFn: ({ folderId, file, description, fileFolderId }: {
      folderId: number;
      file: File;
      description?: string;
      fileFolderId?: number | null;
    }) => uploadFile(folderId, file, description, fileFolderId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['department-files'] });
      queryClient.invalidateQueries({ queryKey: ['department-folders'] });
      queryClient.invalidateQueries({ queryKey: ['department-file-folders'] });
      toast({ title: 'Файл загружен', description: 'Файл успешно загружен в папку отдела.' });
      setUploadDialogOpen(false);
      setSelectedFile(null);
      setUploadDescription('');
    },
    onError: (err: any) => {
      toast({
        title: 'Ошибка загрузки',
        description: err?.response?.data?.detail || 'Не удалось загрузить файл.',
        variant: 'destructive',
      });
    },
  });

  const createFolderMutation = useMutation({
    mutationFn: ({ departmentId, name }: { departmentId: number; name: string }) =>
      createDepartmentFileFolder(departmentId, name),
    onSuccess: (folder) => {
      queryClient.invalidateQueries({ queryKey: ['department-file-folders'] });
      setSelectedFileFolder(folder);
      toast({ title: 'Папка создана', description: `Папка «${folder.name}» добавлена.` });
      setCreateFolderDialogOpen(false);
      setNewFolderName('');
      setSearchQuery('');
    },
    onError: (err: any) => {
      toast({
        title: 'Ошибка создания папки',
        description: err?.response?.data?.detail || 'Не удалось создать папку.',
        variant: 'destructive',
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (fileId: number) => deleteFile(fileId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['department-files'] });
      queryClient.invalidateQueries({ queryKey: ['department-folders'] });
      queryClient.invalidateQueries({ queryKey: ['department-file-folders'] });
      toast({ title: 'Файл удалён', description: 'Файл успешно удалён.' });
      setDeleteDialogOpen(false);
      setFileToDelete(null);
    },
    onError: (err: any) => {
      toast({
        title: 'Ошибка удаления',
        description: err?.response?.data?.detail || 'Не удалось удалить файл.',
        variant: 'destructive',
      });
    },
  });

  /* ---------- Handlers ---------- */

  const handleUpload = useCallback(() => {
    if (!selectedFolder || !selectedFile) return;
    uploadMutation.mutate({
      folderId: selectedFolder.id,
      file: selectedFile,
      description: uploadDescription,
      fileFolderId: selectedFileFolder?.id ?? null,
    });
  }, [selectedFolder, selectedFile, uploadDescription, selectedFileFolder, uploadMutation]);

  const handleCreateFolder = useCallback(() => {
    const name = newFolderName.trim();
    if (!selectedFolder || !name) return;
    createFolderMutation.mutate({ departmentId: selectedFolder.id, name });
  }, [selectedFolder, newFolderName, createFolderMutation]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      setSelectedFile(droppedFile);
      setUploadDialogOpen(true);
    }
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      setSelectedFile(file);
      setUploadDialogOpen(true);
    }
    // Reset the input so re-selecting the *same* file still fires `onChange`
    // (otherwise the dialog won't reopen after closing it).
    e.target.value = '';
  }, []);

  const normalizedSearch = searchQuery.trim().toLowerCase();
  const filteredFiles = files.filter((f) => f.name.toLowerCase().includes(normalizedSearch));
  const filteredFileFolders = selectedFileFolder
    ? []
    : fileFolders.filter((folder) => folder.name.toLowerCase().includes(normalizedSearch));
  const contentLoading = filesLoading || (!selectedFileFolder && fileFoldersLoading);

  /* ---------- Auto-select first folder ---------- */
  React.useEffect(() => {
    if (!selectedFolder && folders.length > 0) {
      setSelectedFolder(folders[0]);
    }
  }, [folders, selectedFolder]);

  React.useEffect(() => {
    setSelectedFileFolder(null);
    setSearchQuery('');
  }, [selectedFolder?.id]);

  /* ---------- Loading State ---------- */

  if (foldersLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-primary/5 flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-10 w-10 animate-spin text-primary" />
          <p className="text-muted-foreground text-sm animate-pulse">Загрузка папок...</p>
        </div>
      </div>
    );
  }

  /* ---------- No folders (no department) ---------- */

  if (folders.length === 0) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-primary/5 flex items-center justify-center p-4">
        <Card className="max-w-md w-full bg-background/60 backdrop-blur-xl border-border/50 shadow-2xl">
          <CardContent className="flex flex-col items-center gap-4 py-12">
            <div className="p-4 rounded-full bg-muted/50">
              <FolderLock className="h-12 w-12 text-muted-foreground" />
            </div>
            <h2 className="text-xl font-semibold text-foreground">Нет доступных папок</h2>
            <p className="text-sm text-muted-foreground text-center max-w-xs">
              Вы не привязаны ни к одному отделу. Обратитесь к HR-менеджеру для назначения в отдел.
            </p>
            <BackToProfile className="mb-0 mt-2" />
          </CardContent>
        </Card>
      </div>
    );
  }

  /* ---------- Main Render ---------- */

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-primary/5">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        className="hidden"
        onChange={handleFileSelect}
      />

      <div className="max-w-7xl mx-auto px-4 py-6 pb-24 md:pb-6">
        {/* ── Header ── */}
        <div className="mb-6 flex flex-col gap-4">
          <BackToProfile className="mb-0" />

          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex items-center gap-3">
              <div className="p-2.5 rounded-xl bg-gradient-to-br from-primary/20 to-primary/10 shadow-lg shadow-primary/5">
                <HardDrive className="h-6 w-6 text-primary" />
              </div>
              <div>
                <h1 className="text-2xl font-bold bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">
                  Файлы отдела
                </h1>
                <p className="text-xs text-muted-foreground mt-0.5">
                  Общий доступ к файлам вашего отдела
                </p>
              </div>
            </div>
            {selectedFolder && (
              <div className="flex flex-wrap gap-2">
                <Button
                  variant="outline"
                  onClick={() => setCreateFolderDialogOpen(true)}
                  className="gap-2 bg-background/70"
                >
                  <FolderPlus className="h-4 w-4" />
                  <span>Создать папку</span>
                </Button>
                <Button
                  onClick={() => fileInputRef.current?.click()}
                  className="gap-2 bg-gradient-to-r from-primary to-primary/80 hover:from-primary/90 hover:to-primary/70 shadow-lg shadow-primary/20 transition-all duration-300 hover:shadow-primary/30 hover:scale-[1.02]"
                >
                  <Upload className="h-4 w-4" />
                  <span>Загрузить файл</span>
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* ── Folder Tabs (for multi-folder users like admin) ── */}
        {folders.length > 1 && (
          <div className="flex gap-2 mb-6 overflow-x-auto pb-2 scrollbar-thin">
            {folders.map((folder) => (
              <button
                key={folder.id}
                onClick={() => setSelectedFolder(folder)}
                className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-sm font-medium transition-all duration-300 whitespace-nowrap ${
                  selectedFolder?.id === folder.id
                    ? 'bg-primary text-primary-foreground shadow-lg shadow-primary/25 scale-[1.02]'
                    : 'bg-background/60 backdrop-blur-sm text-muted-foreground hover:text-foreground hover:bg-background/80 border border-border/50'
                }`}
              >
                <FolderOpen className="h-4 w-4" />
                {folder.department_name}
                <Badge
                  variant="secondary"
                  className={`text-[10px] px-1.5 ${
                    selectedFolder?.id === folder.id
                      ? 'bg-primary-foreground/20 text-primary-foreground'
                      : ''
                  }`}
                >
                  {folder.files_count}
                </Badge>
              </button>
            ))}
          </div>
        )}

        {/* ── Selected folder header ── */}
        {selectedFolder && (
          <Card className="mb-6 bg-gradient-to-r from-primary/5 via-background to-primary/5 border-border/50 backdrop-blur-sm overflow-hidden">
            <CardContent className="py-4">
              <div className="flex items-center justify-between flex-wrap gap-4">
                <div className="flex items-center gap-3">
                  <div className="p-2 rounded-lg bg-primary/10">
                    <FolderOpen className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    {selectedFileFolder && (
                      <button
                        type="button"
                        onClick={() => {
                          setSelectedFileFolder(null);
                          setSearchQuery('');
                        }}
                        className="mb-1 inline-flex items-center gap-1 text-[11px] text-muted-foreground hover:text-foreground"
                      >
                        <ArrowLeft className="h-3 w-3" />
                        {selectedFolder.department_name}
                      </button>
                    )}
                    <h2 className="font-semibold text-foreground">
                      {selectedFileFolder?.name ?? selectedFolder.department_name}
                    </h2>
                    <p className="text-xs text-muted-foreground">
                      {formatFileCount(selectedFileFolder ? files.length : selectedFolder.files_count)}
                    </p>
                  </div>
                </div>
                {/* Search */}
                <div className="relative w-full sm:w-64">
                  <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder={selectedFileFolder ? 'Поиск в папке...' : 'Поиск файлов и папок...'}
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-9 bg-background/60 border-border/50"
                  />
                  {searchQuery && (
                    <button
                      onClick={() => setSearchQuery('')}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                    >
                      <X className="h-3.5 w-3.5" />
                    </button>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* ── Drag & Drop Area + Files ── */}
        {selectedFolder && (
          <div
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            className={`relative min-h-[300px] rounded-2xl transition-all duration-300 ${
              isDragging
                ? 'ring-2 ring-primary ring-offset-2 ring-offset-background bg-primary/5'
                : ''
            }`}
          >
            {/* Drag overlay */}
            {isDragging && (
              <div className="absolute inset-0 z-10 flex items-center justify-center rounded-2xl bg-primary/10 backdrop-blur-sm border-2 border-dashed border-primary">
                <div className="flex flex-col items-center gap-3">
                  <Cloud className="h-12 w-12 text-primary animate-bounce" />
                  <p className="text-primary font-medium">Отпустите файл для загрузки</p>
                </div>
              </div>
            )}

            {contentLoading ? (
              <div className="flex items-center justify-center py-20">
                <Loader2 className="h-8 w-8 animate-spin text-primary" />
              </div>
            ) : filteredFileFolders.length === 0 && filteredFiles.length === 0 ? (
              <Card className="bg-background/40 backdrop-blur-sm border-border/30 border-dashed">
                <CardContent className="flex flex-col items-center gap-4 py-16">
                  <div className="p-4 rounded-full bg-muted/30">
                    {selectedFileFolder ? (
                      <FilePlus className="h-10 w-10 text-muted-foreground/60" />
                    ) : (
                      <FolderPlus className="h-10 w-10 text-muted-foreground/60" />
                    )}
                  </div>
                  <div className="text-center">
                    <p className="text-muted-foreground font-medium">
                      {searchQuery
                        ? 'Ничего не найдено'
                        : selectedFileFolder
                        ? 'Папка пуста'
                        : 'Пока нет файлов и папок'}
                    </p>
                    <p className="text-xs text-muted-foreground/60 mt-1">
                      {searchQuery
                        ? 'Попробуйте изменить поисковый запрос'
                        : selectedFileFolder
                        ? 'Перетащите файл сюда или нажмите «Загрузить файл»'
                        : 'Создайте папку или загрузите файл в корень отдела'}
                    </p>
                  </div>
                  {!searchQuery && (
                    <div className="mt-2 flex flex-wrap justify-center gap-2">
                      {!selectedFileFolder && (
                        <Button
                          variant="outline"
                          onClick={() => setCreateFolderDialogOpen(true)}
                          className="gap-2"
                        >
                          <FolderPlus className="h-4 w-4" />
                          Создать папку
                        </Button>
                      )}
                      <Button
                        variant="outline"
                        onClick={() => fileInputRef.current?.click()}
                        className="gap-2"
                      >
                        <Upload className="h-4 w-4" />
                        Загрузить файл
                      </Button>
                    </div>
                  )}
                </CardContent>
              </Card>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {filteredFileFolders.map((folder, idx) => (
                  <Card
                    key={`folder-${folder.id}`}
                    role="button"
                    tabIndex={0}
                    onClick={() => {
                      setSelectedFileFolder(folder);
                      setSearchQuery('');
                    }}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault();
                        setSelectedFileFolder(folder);
                        setSearchQuery('');
                      }
                    }}
                    className="group cursor-pointer bg-gradient-to-br from-primary/10 to-background backdrop-blur-sm border-border/30 hover:border-primary/40 hover:shadow-lg transition-all duration-300 hover:scale-[1.01] animate-in fade-in-0 slide-in-from-bottom-2"
                    style={{ animationDelay: `${idx * 50}ms`, animationFillMode: 'backwards' }}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-start gap-3">
                        <div className="shrink-0 mt-0.5 rounded-lg bg-primary/10 p-2">
                          <FolderOpen className="h-8 w-8 text-primary" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm text-foreground truncate" title={folder.name}>
                            {folder.name}
                          </p>
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[11px] text-muted-foreground">
                            <span>{formatFileCount(folder.files_count)}</span>
                            <span>•</span>
                            <span>{formatDate(folder.created_at)}</span>
                          </div>
                          {folder.created_by_name && (
                            <p className="text-[11px] text-muted-foreground/70 mt-1 truncate">
                              Создал: {folder.created_by_name}
                            </p>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
                {filteredFiles.map((file, idx) => (
                  <Card
                    key={file.id}
                    className={`group bg-gradient-to-br ${getFileColor(file.name)} backdrop-blur-sm border-border/30 hover:border-border/60 hover:shadow-lg transition-all duration-300 hover:scale-[1.01] animate-in fade-in-0 slide-in-from-bottom-2`}
                    style={{
                      animationDelay: `${(idx + filteredFileFolders.length) * 50}ms`,
                      animationFillMode: 'backwards',
                    }}
                  >
                    <CardContent className="p-4">
                      <div className="flex items-start gap-3">
                        {/* File Icon */}
                        <div className="shrink-0 mt-0.5">{getFileIcon(file.name)}</div>

                        {/* File Info */}
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm text-foreground truncate" title={file.name}>
                            {file.name}
                          </p>
                          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1.5 text-[11px] text-muted-foreground">
                            <span>{formatBytes(file.file_size)}</span>
                            <span>•</span>
                            <span>{formatDate(file.created_at)}</span>
                          </div>
                          {file.uploaded_by_name && (
                            <p className="text-[11px] text-muted-foreground/70 mt-1 truncate">
                              👤 {file.uploaded_by_name}
                            </p>
                          )}
                          {file.description && (
                            <p className="text-[11px] text-muted-foreground/60 mt-1 line-clamp-2">
                              {file.description}
                            </p>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex flex-col gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-200">
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-primary"
                            onClick={() => {
                              if (file.file_url) downloadFileUrl(file.file_url);
                            }}
                            title="Скачать"
                          >
                            <Download className="h-4 w-4" />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-8 w-8 text-muted-foreground hover:text-destructive"
                            onClick={() => {
                              setFileToDelete(file);
                              setDeleteDialogOpen(true);
                            }}
                            title="Удалить"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </div>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── Create Folder Dialog ── */}
      <Dialog
        open={createFolderDialogOpen}
        onOpenChange={(open) => {
          setCreateFolderDialogOpen(open);
          if (!open) setNewFolderName('');
        }}
      >
        <DialogContent className="sm:max-w-md bg-background/95 backdrop-blur-xl border-border/50">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <FolderPlus className="h-5 w-5 text-primary" />
              Создать папку
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-2 py-2">
            <label className="text-sm font-medium text-foreground">Название папки</label>
            <Input
              autoFocus
              placeholder="Например, Регламенты"
              value={newFolderName}
              onChange={(event) => setNewFolderName(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  handleCreateFolder();
                }
              }}
              className="bg-background/60 border-border/50"
            />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setCreateFolderDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleCreateFolder}
              disabled={!newFolderName.trim() || createFolderMutation.isPending}
              className="gap-2 bg-gradient-to-r from-primary to-primary/80"
            >
              {createFolderMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <FolderPlus className="h-4 w-4" />
              )}
              Создать
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Upload Dialog ── */}
      <Dialog open={uploadDialogOpen} onOpenChange={setUploadDialogOpen}>
        <DialogContent className="sm:max-w-md bg-background/95 backdrop-blur-xl border-border/50">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Upload className="h-5 w-5 text-primary" />
              Загрузить файл
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2 min-w-0">
            {selectedFile && (
              <div className="flex items-center gap-3 p-3 rounded-lg bg-muted/30 border border-border/30 min-w-0">
                {getFileIcon(selectedFile.name)}
                <div className="flex-1 min-w-0">
                  <p className="flex text-sm font-medium min-w-0" title={selectedFile.name}>
                    <span className="truncate min-w-0">{splitFileName(selectedFile.name).base}</span>
                    <span className="shrink-0 whitespace-pre">{splitFileName(selectedFile.name).ext}</span>
                  </p>
                  <p className="text-xs text-muted-foreground">{formatBytes(selectedFile.size)}</p>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={() => setSelectedFile(null)}
                >
                  <X className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}
            {!selectedFile && (
              <div
                className="flex flex-col items-center gap-3 p-6 rounded-lg border-2 border-dashed border-border/50 cursor-pointer hover:border-primary/50 transition-colors"
                onClick={() => fileInputRef.current?.click()}
              >
                <Cloud className="h-8 w-8 text-muted-foreground" />
                <p className="text-sm text-muted-foreground">Нажмите для выбора файла</p>
              </div>
            )}
            <div className="space-y-2">
              <label className="text-sm font-medium text-foreground">
                Описание <span className="text-muted-foreground">(необязательно)</span>
              </label>
              <Textarea
                placeholder="Краткое описание файла..."
                value={uploadDescription}
                onChange={(e) => setUploadDescription(e.target.value)}
                rows={2}
                className="resize-none bg-background/60 border-border/50"
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setUploadDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={handleUpload}
              disabled={!selectedFile || uploadMutation.isPending}
              className="gap-2 bg-gradient-to-r from-primary to-primary/80"
            >
              {uploadMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Upload className="h-4 w-4" />
              )}
              Загрузить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete Confirmation Dialog ── */}
      <Dialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
        <DialogContent className="sm:max-w-sm bg-background/95 backdrop-blur-xl border-border/50">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-destructive">
              <Trash2 className="h-5 w-5" />
              Удалить файл?
            </DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground py-2">
            Файл <strong className="text-foreground">{fileToDelete?.name}</strong> будет удалён
            безвозвратно.
          </p>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setDeleteDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="destructive"
              onClick={() => fileToDelete && deleteMutation.mutate(fileToDelete.id)}
              disabled={deleteMutation.isPending}
              className="gap-2"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
              Удалить
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default DepartmentFiles;
