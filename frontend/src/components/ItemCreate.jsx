import React, { useState } from 'react';
import api from '../api/client';
import { apiPath } from '../api/endpoints';

function ItemCreate({ onItemCreated }) {
    const [title, setTitle] = useState('');
    const [description, setDescription] = useState('');

    const handleSubmit = async (e) => {
        e.preventDefault();
        try {
            await api.post(apiPath('users', 'items/'), { title, description });
            setTitle('');
            setDescription('');
            if (onItemCreated) onItemCreated();
        } catch (err) {
            console.error(err);
            alert('Failed to create item');
        }
    };

    return (
        <form onSubmit={handleSubmit} className="p-4 border rounded shadow-md max-w-sm mx-auto mt-4">
            <h2 className="text-xl mb-4">Create New Item</h2>
            <div className="mb-4">
                <label className="block mb-1">Title</label>
                <input
                    type="text"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    className="w-full p-2 border rounded"
                    required
                />
            </div>
            <div className="mb-4">
                <label className="block mb-1">Description</label>
                <textarea
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    className="w-full p-2 border rounded"
                />
            </div>
            <button type="submit" className="w-full bg-green-500 text-white p-2 rounded hover:bg-green-600">
                Create Item
            </button>
        </form>
    );
}

export default ItemCreate;
