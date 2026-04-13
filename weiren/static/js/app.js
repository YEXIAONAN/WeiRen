document.addEventListener('DOMContentLoaded', () => {
  const fileInput = document.getElementById('file-input');
  const fileCount = document.getElementById('file-count');

  if (fileInput && fileCount) {
    const updateCount = () => {
      const count = fileInput.files ? fileInput.files.length : 0;
      fileCount.textContent = count > 0 ? `已选择 ${count} 个文件` : '未选择文件';
    };

    fileInput.addEventListener('change', updateCount);
    updateCount();
  }
});
