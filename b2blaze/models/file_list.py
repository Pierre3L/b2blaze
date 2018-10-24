"""
Copyright George Sibble 2018
"""

from ..b2_exceptions import B2InvalidBucketName, B2InvalidBucketConfiguration, B2BucketCreationError
from .b2_file import B2File
from ..utilities import b2_url_encode, get_content_length, get_part_ranges, decode_error, RangeStream, StreamWithHashProgress
from ..b2_exceptions import B2RequestError, B2FileNotFound
from multiprocessing.dummy import Pool as ThreadPool
from ..api import BucketAPI, FileAPI

class B2FileList(object):
    """

    """
    def __init__(self, connector, bucket):
        """

        :param connector:
        :param bucket:
        """
        self.connector = connector
        self.bucket = bucket
        self._files_by_name = {}
        self._files_by_id = {}

    def all(self):
        """

        :return:
        """
        return self._update_files_list(retrieve=True)

    def _update_files_list(self, retrieve=False):
        """

        :param retrieve:
        :return:
        """
        path = BucketAPI.list_files
        files = []
        new_files_to_retrieve = True
        params = {
            'bucketId': self.bucket.bucket_id,
            'maxFileCount': 10000
        }
        while new_files_to_retrieve:
            response = self.connector.make_request(path=path, method='post', params=params)
            if response.status_code == 200:
                files_json = response.json()
                self._files_by_name = {}
                self._files_by_id = {}
                for file_json in files_json['files']:
                    new_file = B2File(connector=self.connector, parent_list=self, **file_json)
                    files.append(new_file)
                    self._files_by_name[file_json['fileName']] = new_file
                    self._files_by_id[file_json['fileId']] = new_file
                if files_json['nextFileName'] is None:
                    new_files_to_retrieve = False
                else:
                    params['startFileName'] = files_json['nextFileName']
            else:
                raise B2RequestError(decode_error(response))
        if retrieve:
            return files

    def file_versions_by_id(self, file_id, file_name):
        """ Return all the versions of all files in a given bucket. 
            Returns dict: 
                'file_name':        (str) Filename
                'file_id':          (str) File ID
        """ 
        return self._get_file_versions(file_id, file_name)


    def all_file_versions(self):
        """ Return all the versions of all files in a given bucket. 
            Returns dict: 
                'file_names':       (list) String filenames
                'file_versions':    (list) b2blaze File objects
        """ 
        return self._get_file_versions()

    def _get_file_versions(self, file_id=None, file_name=None):
        """ Internal method. Return all the versions of all files in a given bucket, or single version history.

            Params:
                file_id:            (str) File id (optional, required if requesting single file versions)
                file_name:          (str) File id (optional, required if requesting single file versions)

            Returns dict: 
                'file_names':       (list) String filenames
                'file_versions':    (list) b2blaze File objects
        """ 

        path = BucketAPI.list_file_versions
        file_versions = dict()
        file_names = []
        new_files_to_retrieve = True
        params = {
            'bucketId': self.bucket.bucket_id,
            'maxFileCount': 10000
        }

        # If specified file ID, we only want files which match
        if file_id:
            params['startFileId'] = file_id
            params['startFileName'] = file_name
            params['maxFileCount'] = 1

        while new_files_to_retrieve:
            if file_id: new_files_to_retrieve = False   # Avoid infinite loops destroying your API limit :)

            response = self.connector.make_request(path=path, method='post', params=params)
            if response.status_code == 200:
                files_json = response.json()
                for file_json in files_json['files']:
                    new_file = B2File(connector=self.connector, parent_list=self, **file_json)
                    file_name, file_id = file_json['fileName'], file_json['fileId']
                    file_names.append(file_name)
                    
                    # Add file to list keyed by file_id
                    if file_id in file_versions:
                        file_versions[file_id].append(new_file)
                    else:
                        file_versions[file_id] = [new_file]

                if files_json['nextFileName'] is None:
                    new_files_to_retrieve = False
                else:
                    params['startFileName'] = files_json['nextFileName']
            else:
                raise B2RequestError(decode_error(response))
        return {'file_names': file_names, 'file_versions': file_versions}


    def get(self, file_name=None, file_id=None):
        """

        :param file_name:
        :param file_id:
        :return:
        """
        if file_name is not None:
            path = BucketAPI.list_files
            params = {
                'prefix': b2_url_encode(file_name),
                'bucketId': self.bucket.bucket_id
            }

            response = self.connector.make_request(path, method='post', params=params)
            if response.status_code == 200:
                file_json = response.json()
                if len(file_json['files']) > 0:
                    return B2File(connector=self.connector, parent_list=self, **file_json['files'][0])
                else:
                    raise B2FileNotFound('fileName - ' + file_name)
            else:
                raise B2RequestError(decode_error(response))
        elif file_id is not None:
            path = FileAPI.file_info
            params = {
                'fileId': file_id
            }
            response = self.connector.make_request(path, method='post', params=params)
            if response.status_code == 200:
                file_json = response.json()
                return B2File(connector=self.connector, parent_list=self, **file_json)
            else:
                raise B2RequestError(decode_error(response))
        else:
            raise ValueError('file_name or file_id must be passed')


    def upload(self, contents, file_name, mime_content_type=None, content_length=None, progress_listener=None):
        """

        :param contents:
        :param file_name:
        :param mime_content_type:
        :param content_length:
        :param progress_listener:
        :return:
        """
        if file_name[0] == '/':
            file_name = file_name[1:]
        get_upload_url_path = BucketAPI.upload_url
        params = {
            'bucketId': self.bucket.bucket_id
        }
        upload_url_response = self.connector.make_request(path=get_upload_url_path, method='post', params=params)
        if upload_url_response.status_code == 200:
            upload_url = upload_url_response.json().get('uploadUrl', None)
            auth_token = upload_url_response.json().get('authorizationToken', None)
            upload_response = self.connector.upload_file(file_contents=contents, file_name=file_name,
                                                         upload_url=upload_url, auth_token=auth_token,
                                                         content_length=content_length, progress_listener=progress_listener)
            if upload_response.status_code == 200:
                new_file = B2File(connector=self.connector, parent_list=self, **upload_response.json())
                # Update file list after upload
                self._update_files_list()
                return new_file
            else:
                raise B2RequestError(decode_error(upload_response))
        else:
            raise B2RequestError(decode_error(upload_url_response))

    def upload_large_file(self, contents, file_name, part_size=None, num_threads=4,
                          mime_content_type=None, content_length=None, progress_listener=None):
        """

        :param contents:
        :param file_name:
        :param part_size:
        :param num_threads:
        :param mime_content_type:
        :param content_length:
        :param progress_listener:
        :return:
        """
        if file_name[0] == '/':
            file_name = file_name[1:]
        if part_size == None:
            part_size = self.connector.recommended_part_size
        if content_length == None:
            content_length = get_content_length(contents)
        start_large_file_path = BucketAPI.upload_large
        params = {
            'bucketId': self.bucket.bucket_id,
            'fileName': b2_url_encode(file_name),
            'contentType': mime_content_type or 'b2/x-auto'
        }
        large_file_response = self.connector.make_request(path=start_large_file_path, method='post', params=params)
        if large_file_response.status_code == 200:
            file_id = large_file_response.json().get('fileId', None)
            get_upload_part_url_path = BucketAPI.upload_large_part
            params = {
                'fileId': file_id
            }
            pool = ThreadPool(num_threads)
            def upload_part_worker(args):
                part_number, part_range = args
                offset, content_length = part_range
                with open(contents.name, 'rb') as file:
                    file.seek(offset)
                    stream = RangeStream(file, offset, content_length)
                    upload_part_url_response = self.connector.make_request(path=get_upload_part_url_path, method='post', params=params)
                    if upload_part_url_response.status_code == 200:
                        upload_url = upload_part_url_response.json().get('uploadUrl')
                        auth_token = upload_part_url_response.json().get('authorizationToken')
                        upload_part_response = self.connector.upload_part(file_contents=stream, content_length=content_length,
                                                                          part_number=part_number, upload_url=upload_url,
                                                                          auth_token=auth_token, progress_listener=progress_listener)
                        if upload_part_response.status_code == 200:
                            return upload_part_response.json().get('contentSha1', None)
                        else:
                            raise B2RequestError(decode_error(upload_part_response))
                    else:
                        raise B2RequestError(decode_error(upload_part_url_response))
            sha_list = pool.map(upload_part_worker, enumerate(get_part_ranges(content_length, part_size), 1))
            pool.close()
            pool.join()
            finish_large_file_path = BucketAPI.upload_large_finish
            params = {
                'fileId': file_id,
                'partSha1Array': sha_list
            }
            finish_large_file_response = self.connector.make_request(path=finish_large_file_path, method='post', params=params)
            if finish_large_file_response.status_code == 200:
                new_file = B2File(connector=self.connector, parent_list=self, **finish_large_file_response.json())
                return new_file
            else:
                raise B2RequestError(decode_error(finish_large_file_response))
        else:
            raise B2RequestError(decode_error(large_file_response))
